import importlib.util
import multiprocessing
import os
import subprocess
import sys
import uuid

from fastapi import HTTPException

from src.message_protocol import normalize_envelope
from src.node_capabilities import NODE_CAPABILITY_LIST

from .node_runtime_event_sink import NodeRuntimeEventSink
from .route_parser import NodeRouteParser
from .runtime_paths import _get_nodes_dir, _get_resource_root, _get_runtime_root
from .state_store import _transition_node_config_to_idle, _write_json_dict


def _read_tail_text(file_path: str, max_chars: int = 20000) -> str:
    if not file_path or not os.path.exists(file_path):
        return ""
    try:
        size = os.path.getsize(file_path)
        with open(file_path, "rb") as f:
            if size > max_chars:
                f.seek(-max_chars, os.SEEK_END)
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except Exception:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()[-max_chars:]
        except Exception:
            return ""


def _read_node_capabilities(node: object, context: dict | None = None) -> tuple[list[str], list[str]]:
    accepts: list[str] = []
    produces: list[str] = []
    get_caps = getattr(node, "get_capabilities", None)
    if callable(get_caps):
        try:
            caps = get_caps(context if isinstance(context, dict) else None)
        except Exception:
            caps = None
        if isinstance(caps, dict):
            accepts = NODE_CAPABILITY_LIST.parse(caps.get("accepts"))
            produces = NODE_CAPABILITY_LIST.parse(caps.get("produces"))
    if not accepts:
        accepts = NODE_CAPABILITY_LIST.parse(getattr(node, "input_capabilities", []))
    if not produces:
        produces = NODE_CAPABILITY_LIST.parse(getattr(node, "output_capabilities", []))
    if not accepts:
        accepts = ["text"]
    if not produces:
        produces = ["text"]
    return accepts, produces


def _run_node_logic(nodes_dir: str, node_id: str, message: object, context: dict | None = None) -> str:
    routed = _run_node_logic_with_routes(nodes_dir, node_id, message, context)
    return str((routed or {}).get("text") or "")


def _run_node_logic_with_routes(nodes_dir: str, node_id: str, message: object, context: dict | None = None) -> dict:
    if not nodes_dir:
        raise HTTPException(status_code=404, detail="nodes directory not found")
    file_path = os.path.join(nodes_dir, f"{node_id}.py")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="node not found")

    runtime_root = _get_runtime_root()
    if runtime_root and runtime_root not in sys.path:
        sys.path.insert(0, runtime_root)
    resource_root = _get_resource_root()
    if resource_root and resource_root not in sys.path:
        sys.path.insert(0, resource_root)

    spec = importlib.util.spec_from_file_location(f"nodes_{node_id}", file_path)
    if not spec or not spec.loader:
        raise HTTPException(status_code=500, detail="failed to load node")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    node_cls = getattr(module, "Node", None)
    if node_cls is None:
        raise HTTPException(status_code=400, detail="Node class not found")
    node = node_cls()
    if not hasattr(node, "on_input"):
        raise HTTPException(status_code=400, detail="Node.on_input not found")

    base_context = {"node_id": node_id}
    if isinstance(context, dict):
        base_context = {**context, "node_id": node_id}
    input_message = normalize_envelope(message, default_role="user")

    persist_input_fn = getattr(node, "_persist_input_default", None)
    item_source = str(base_context.get("source") or "").strip()
    # Skip re-persisting the user input when it was already written by emit_graph().
    if callable(persist_input_fn) and item_source != "emit":
        try:
            persist_input_fn(input_message, base_context)
        except Exception:
            pass

    on_input_fn = getattr(node, "on_input", None)
    if callable(on_input_fn):
        output = on_input_fn(input_message, base_context)
    else:
        raise HTTPException(status_code=400, detail="Node.on_input not found")

    parsed_output = NodeRouteParser.parse_node_output(output)
    output_text = "" if parsed_output.get("display_text") is None else str(parsed_output.get("display_text"))
    routes = parsed_output.get("routes") if isinstance(parsed_output, dict) else []
    if not isinstance(routes, list):
        routes = []
    output_message = normalize_envelope(parsed_output.get("display_message"), default_role="assistant")
    memory_sidecars = parsed_output.get("memory_sidecars") if isinstance(parsed_output, dict) else []
    if not isinstance(memory_sidecars, list):
        memory_sidecars = []

    return {
        "text": output_text,
        "message": output_message,
        "routes": routes,
        "memory_sidecars": memory_sidecars,
    }


def _list_node_metas(nodes_dir: str) -> list[dict]:
    nodes: list[dict] = []
    if not nodes_dir or not os.path.isdir(nodes_dir):
        return nodes

    runtime_root = _get_runtime_root()
    if runtime_root and runtime_root not in sys.path:
        sys.path.insert(0, runtime_root)
    resource_root = _get_resource_root()
    if resource_root and resource_root not in sys.path:
        sys.path.insert(0, resource_root)

    for filename in os.listdir(nodes_dir):
        if not filename.endswith(".py"):
            continue
        if filename in {"__init__.py", "base_node.py"}:
            continue
        node_id = filename[:-3]
        node_name = node_id
        node_description = ""
        input_num = 1
        output_num = 1
        accepts = ["text"]
        produces = ["text"]
        file_path = os.path.join(nodes_dir, filename)
        has_node_class = False
        if os.path.exists(file_path):
            try:
                module_name = f"nodes_meta_{node_id}_{uuid.uuid4().hex}"
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    node_cls = getattr(module, "Node", None)
                    if node_cls is not None:
                        has_node_class = True
                        node = node_cls()
                        node_name = str(getattr(node, "name", node_id) or node_id)
                        node_description = str(getattr(node, "description", "") or "")
                        get_input_num = getattr(node, "getInputNum", None)
                        if callable(get_input_num):
                            try:
                                input_num = NodeRouteParser.parse_port_count(get_input_num(None), default=1)
                            except Exception:
                                try:
                                    input_num = NodeRouteParser.parse_port_count(get_input_num(), default=1)
                                except Exception:
                                    input_num = 1
                        get_output_num = getattr(node, "getOutputNum", None)
                        if callable(get_output_num):
                            try:
                                output_num = NodeRouteParser.parse_port_count(get_output_num(None), default=1)
                            except Exception:
                                try:
                                    output_num = NodeRouteParser.parse_port_count(get_output_num(), default=1)
                                except Exception:
                                    output_num = 1
                        accepts, produces = _read_node_capabilities(node, None)
            except Exception:
                pass
        if not has_node_class:
            continue
        nodes.append(
            {
                "id": node_id,
                "name": node_name,
                "description": node_description,
                "input_num": input_num,
                "output_num": output_num,
                "accepts": accepts,
                "produces": produces,
            }
        )
    nodes.sort(key=lambda item: item["name"].lower())
    return nodes


def _node_worker(
    nodes_dir: str,
    node_id: str,
    message: object,
    context: dict | None,
    result_queue: multiprocessing.Queue,
    node_config_path: str | None = None,
) -> None:
    worker_context = dict(context) if isinstance(context, dict) else None
    if isinstance(node_config_path, str) and node_config_path and isinstance(worker_context, dict):
        graph_id = str(worker_context.get("graph_id") or "default").strip() or "default"
        node_instance_id = str(worker_context.get("node_instance_id") or node_id).strip() or node_id
        node_type_id = str(worker_context.get("node_type_id") or node_id).strip() or node_id

        def _noop_log_graph_event(*args, **kwargs) -> None:
            return None

        def _noop_append_tool_call_entry(*args, **kwargs) -> None:
            return None

        runtime_event_sink = NodeRuntimeEventSink(
            graph_id=graph_id,
            node_id=node_instance_id,
            node_type_id=node_type_id,
            config_path=node_config_path,
            trace_id=str(worker_context.get("trace_id") or ""),
            depth=0,
            stream_last_text="",
            log_graph_event=_noop_log_graph_event,
            append_tool_call_entry=_noop_append_tool_call_entry,
        )
        worker_context["stream_callback"] = runtime_event_sink.handle

    try:
        routed = _run_node_logic_with_routes(nodes_dir, node_id, message, worker_context)
        output = str((routed or {}).get("text") or "")
        output_message = normalize_envelope((routed or {}).get("message"), default_role="assistant")
        result_queue.put({"status": "finished", "output": output, "output_message": output_message})
    except Exception as e:
        result_queue.put({"status": "error", "error": str(e)})
    finally:
        if isinstance(node_config_path, str) and node_config_path:
            _transition_node_config_to_idle(node_config_path)


def _kill_pid(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        if os.name == "nt":
            completed = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
            return completed.returncode == 0
        os.kill(pid, 15)
        return True
    except Exception:
        return False
