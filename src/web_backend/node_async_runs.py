import os
import queue
import uuid

from fastapi import Request

from . import runtime_paths
from .node_execution_context import bind_node_storage_context
from .node_state_machine import parse_node_state
from .service_host import HostBoundService
from .shared import (
    HTTPException,
    _read_json_dict,
    _set_node_config_last_message,
    _touch_node_config_last_run_at,
    _transition_node_config_to_idle,
    _update_node_config_state,
    _node_worker,
    envelope_preview,
    envelope_text,
    normalize_envelope,
)


class NodeAsyncRuns(HostBoundService):
    def run_node_async(self, payload: dict, request: Request = None):
        node_id = (payload or {}).get("node_id")
        message = (payload or {}).get("input")
        context = (payload or {}).get("context")
        if not isinstance(node_id, str) or not node_id.strip():
            raise HTTPException(status_code=400, detail="node_id is required")
        if message is None:
            raise HTTPException(status_code=400, detail="input is required")
        if context is not None and not isinstance(context, dict):
            raise HTTPException(status_code=400, detail="context must be object")
        context = dict(context or {})
        message = normalize_envelope(message, default_role="user")
        message_full = envelope_text(message).strip()
        message_preview = envelope_preview(message)

        nodes_dir = runtime_paths._get_nodes_dir()
        if not nodes_dir:
            raise HTTPException(status_code=404, detail="nodes directory not found")

        node_config_path = None
        safe_graph_id = ""
        safe_node_instance_id = ""
        if context:
            graph_id = context.get("graph_id")
            node_instance_id = context.get("node_instance_id")
            if isinstance(graph_id, str) and graph_id.strip() and isinstance(node_instance_id, str) and node_instance_id.strip():
                safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
                safe_node_instance_id = self.graph_runtime._sanitize_node_id(node_instance_id)
                self.core.node_ops.require_node_visible(safe_node_instance_id, safe_graph_id, request)
                node_config_path = self.graph_runtime._node_config_path(safe_node_instance_id, safe_graph_id)
                if node_config_path and os.path.exists(node_config_path):
                    current = _read_json_dict(node_config_path)
                    if bool((current or {}).get("_delete_requested")):
                        raise HTTPException(status_code=409, detail="node is being deleted")
                    if parse_node_state(current.get("state")) == "stop":
                        raise HTTPException(status_code=409, detail="node is stopped")
                    _update_node_config_state(node_config_path, "working")
                    _set_node_config_last_message(node_config_path, message_full or message_preview)
                    if isinstance(current, dict):
                        self.graph_runtime._inject_node_config_into_context(context, current)
                    bind_node_storage_context(context, node_config_path)

        run_id = str(uuid.uuid4())
        context["task_id"] = run_id
        result_queue = self.mp_ctx.Queue()
        process = self.mp_ctx.Process(
            target=_node_worker,
            args=(nodes_dir, node_id, message, context, result_queue, node_config_path),
        )
        process.start()
        self.node_runs[run_id] = {
            "process": process,
            "queue": result_queue,
            "status": "running",
            "output": None,
            "error": None,
            "input": message,
            "node_config_path": node_config_path,
            "graph_id": safe_graph_id,
            "node_instance_id": safe_node_instance_id,
        }
        return {"run_id": run_id}

    def get_node_run(self, run_id: str, request: Request = None):
        run = self.node_runs.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        graph_id = str(run.get("graph_id") or "").strip()
        node_instance_id = str(run.get("node_instance_id") or "").strip()
        if graph_id and node_instance_id:
            self.core.node_ops.require_node_visible(node_instance_id, graph_id, request)

        if run["status"] == "running":
            try:
                result = run["queue"].get_nowait()
            except queue.Empty:
                result = None

            if result:
                if result.get("status") == "finished":
                    run["status"] = "finished"
                    run["output"] = result.get("output", "")
                    run["output_message"] = normalize_envelope(result.get("output_message"), default_role="assistant")
                else:
                    run["status"] = "error"
                    run["error"] = result.get("error", "node run failed")
                cfg_path = run.get("node_config_path")
                if isinstance(cfg_path, str) and cfg_path:
                    _transition_node_config_to_idle(cfg_path)
                    if run["status"] == "finished":
                        output_full = envelope_text(run.get("output_message")).strip() or str(run.get("output") or "").strip()
                        if not output_full:
                            output_full = envelope_text(run.get("input")).strip() or envelope_preview(run.get("input"))
                        _set_node_config_last_message(cfg_path, output_full)
                        _touch_node_config_last_run_at(cfg_path)
                try:
                    run["process"].join(timeout=0.1)
                except Exception:
                    pass
            elif not run["process"].is_alive():
                run["status"] = "error"
                run["error"] = "node process stopped"
                cfg_path = run.get("node_config_path")
                if isinstance(cfg_path, str) and cfg_path:
                    _transition_node_config_to_idle(cfg_path)

        payload = {"status": run["status"]}
        if run["status"] == "finished":
            payload["output"] = run.get("output") or ""
            payload["message"] = normalize_envelope(run.get("output_message"), default_role="assistant")
        if run["status"] == "error":
            payload["error"] = run.get("error") or "node run failed"
        return payload
