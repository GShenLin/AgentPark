import importlib.util
import multiprocessing
import os
import subprocess
import sys
import uuid

from fastapi import HTTPException

from src.message_protocol import normalize_envelope

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


def _normalize_capability_list(values: object) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output


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
            accepts = _normalize_capability_list(caps.get("accepts"))
            produces = _normalize_capability_list(caps.get("produces"))
    if not accepts:
        accepts = _normalize_capability_list(getattr(node, "input_capabilities", []))
    if not produces:
        produces = _normalize_capability_list(getattr(node, "output_capabilities", []))
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
    if callable(persist_input_fn):
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

    return {
        "text": output_text,
        "message": output_message,
        "routes": routes,
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
        if os.path.exists(file_path):
            try:
                module_name = f"nodes_meta_{node_id}_{uuid.uuid4().hex}"
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    node_cls = getattr(module, "Node", None)
                    if node_cls is not None:
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
    try:
        routed = _run_node_logic_with_routes(nodes_dir, node_id, message, context)
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
