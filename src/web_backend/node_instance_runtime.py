import json
import math
import os
import time

from src.clock_config import build_clock_interval_fields, parse_clock_interval_seconds

from . import node_runtime, runtime_paths
from .service_host import HostBoundService
from .shared import (
    HTTPException,
    _parse_node_state,
    _read_json_dict,
    _read_tail_text,
    _set_node_config_last_message,
    _touch_node_config_last_run_at,
    _update_node_config_state,
    _write_json_dict,
    envelope_preview,
    envelope_text,
    normalize_envelope,
)


class NodeInstanceRuntime(HostBoundService):
    def _read_clock_interval_seconds(self, cfg: dict) -> int:
        return parse_clock_interval_seconds(cfg)

    def _control_clock_node(self, config_path: str, cfg: dict, action: str) -> dict:
        interval_seconds = self._read_clock_interval_seconds(cfg)
        if interval_seconds <= 0:
            raise HTTPException(status_code=400, detail="clock interval must be greater than 0")

        now_ts = time.time()
        next_cfg = dict(cfg)
        next_cfg.update(build_clock_interval_fields(next_cfg))
        if action == "start":
            current_state = _parse_node_state(next_cfg.get("state"))
            if current_state == "stop":
                remaining_raw = next_cfg.get("_clock_remaining_seconds")
                try:
                    remaining_seconds = int(float(remaining_raw))
                except Exception:
                    remaining_seconds = 0
                if remaining_seconds <= 0:
                    remaining_seconds = interval_seconds
            else:
                remaining_seconds = interval_seconds
                next_cfg["_clock_trigger_count"] = 0
            next_cfg["_clock_running"] = True
            next_cfg["_clock_remaining_seconds"] = remaining_seconds
            next_cfg["_clock_next_fire_at"] = now_ts + float(remaining_seconds)
            next_cfg["state"] = "working"
            next_cfg["last_message"] = f"Working: {remaining_seconds}s"
        elif action == "stop":
            next_fire_at_raw = next_cfg.get("_clock_next_fire_at")
            try:
                next_fire_at = float(next_fire_at_raw)
            except Exception:
                next_fire_at = now_ts + float(interval_seconds)
            remaining_seconds = max(0, int(math.ceil(next_fire_at - now_ts)))
            next_cfg["_clock_running"] = False
            next_cfg["_clock_remaining_seconds"] = remaining_seconds
            next_cfg["_clock_next_fire_at"] = None
            next_cfg["state"] = "stop"
            next_cfg["last_message"] = f"Paused: {remaining_seconds}s" if remaining_seconds > 0 else "Paused"
        else:
            raise HTTPException(status_code=400, detail="unsupported clock action")

        if not _write_json_dict(config_path, next_cfg):
            raise HTTPException(status_code=500, detail="failed to write node config")
        return {"ok": True, "state": _parse_node_state(next_cfg.get("state")), "config": next_cfg}

    def run_node(self, payload: dict):
        node_id = (payload or {}).get("node_id")
        message = (payload or {}).get("input")
        context = (payload or {}).get("context")
        if not isinstance(node_id, str) or not node_id.strip():
            raise HTTPException(status_code=400, detail="node_id is required")
        if message is None:
            raise HTTPException(status_code=400, detail="input is required")
        if context is not None and not isinstance(context, dict):
            raise HTTPException(status_code=400, detail="context must be object")
        message = normalize_envelope(message, default_role="user")
        message_full = envelope_text(message).strip()
        message_preview = envelope_preview(message)

        try:
            node_config_path = None
            if isinstance(context, dict):
                graph_id = context.get("graph_id")
                node_instance_id = context.get("node_instance_id")
                if isinstance(graph_id, str) and graph_id.strip() and isinstance(node_instance_id, str) and node_instance_id.strip():
                    safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
                    safe_node_instance_id = self.graph_runtime._sanitize_node_id(node_instance_id)
                    node_config_path = self.graph_runtime._node_config_path(safe_node_instance_id, safe_graph_id)
                    if node_config_path and os.path.exists(node_config_path):
                        current = _read_json_dict(node_config_path)
                        if isinstance(current, dict):
                            self.graph_runtime._inject_node_config_into_context(context, current)
                        _set_node_config_last_message(node_config_path, message_full or message_preview)
            routed = node_runtime._run_node_logic_with_routes(runtime_paths._get_nodes_dir(), node_id, message, context)
            output = str((routed or {}).get("text") or "")
            output_message = normalize_envelope((routed or {}).get("message"), default_role="assistant")
            if isinstance(node_config_path, str) and node_config_path:
                output_full = envelope_text(output_message).strip()
                final_message = output_full or message_full or envelope_preview(output_message) or message_preview
                _set_node_config_last_message(node_config_path, final_message)
                _touch_node_config_last_run_at(node_config_path)
            return {"output": output, "message": output_message}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def get_node_instance_memory(self, node_id: str, max_chars: int = 20000, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        memory_path = self.graph_runtime._node_memory_path(safe_node_id, safe_graph_id)
        messages_path = self.graph_runtime._node_messages_path(safe_node_id, safe_graph_id)
        cfg = _read_json_dict(config_path) if isinstance(config_path, str) and config_path and os.path.exists(config_path) else {}
        if not isinstance(cfg, dict) or not cfg:
            raise HTTPException(status_code=404, detail="node instance not found")
        text = _read_tail_text(memory_path, max_chars=max_chars) if memory_path and os.path.exists(memory_path) else ""
        messages: list[dict] = []
        if messages_path and os.path.exists(messages_path):
            try:
                with open(messages_path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f.readlines()[-400:]:
                        raw = str(line or "").strip()
                        if raw:
                            item = json.loads(raw)
                            if isinstance(item, dict):
                                messages.append(normalize_envelope(item, default_role="assistant"))
            except Exception:
                messages = []
        return {
            "memory_path": memory_path,
            "messages_path": messages_path,
            "text": text,
            "messages": messages,
            "state": _parse_node_state(cfg.get("state")) if isinstance(cfg, dict) else "idle",
            "last_message": str(cfg.get("last_message") or "") if isinstance(cfg, dict) else "",
        }

    def set_node_instance_state(self, node_id: str, payload: dict, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        if not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")
        mapped = _parse_node_state((payload or {}).get("state"))
        _update_node_config_state(config_path, mapped)
        self.graph_runtime._log_graph_event(safe_graph_id, "node_state_set", node_id=safe_node_id, state=mapped)
        if mapped == "idle":
            self.graph_runtime._ensure_graph_runner(safe_graph_id)
            self.graph_runtime._wake_graph_runner(safe_graph_id)
        return {"ok": True, "state": mapped}

    def control_node_instance(self, node_id: str, payload: dict, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        if not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")
        cfg = _read_json_dict(config_path)
        if not isinstance(cfg, dict) or not cfg:
            raise HTTPException(status_code=404, detail="node instance not found")

        action = str((payload or {}).get("action") or "").strip().lower()
        type_id = str(cfg.get("type_id") or "").strip()
        if type_id != "clock_node":
            raise HTTPException(status_code=400, detail="node control is not supported for this node type")
        if action not in {"start", "stop"}:
            raise HTTPException(status_code=400, detail="action is required")

        result = self._control_clock_node(config_path, cfg, action)
        self.graph_runtime._log_graph_event(
            safe_graph_id,
            "node_control",
            node_id=safe_node_id,
            node_type_id=type_id,
            action=action,
            state=str((result.get("config") or {}).get("state") or ""),
        )
        if action == "start":
            self.graph_runtime._ensure_graph_runner(safe_graph_id)
            self.graph_runtime._wake_graph_runner(safe_graph_id)
        return {"ok": True, "state": result.get("state")}
