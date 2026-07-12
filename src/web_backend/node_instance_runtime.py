import json
import math
import os
import time

from fastapi.responses import StreamingResponse

from src.clock_config import build_clock_interval_fields, parse_clock_interval_seconds
from src.console_interactive_sessions import send_console_interactive_input

from . import node_runtime, runtime_paths
from .channel_api import call_channel_http
from .node_state_machine import parse_node_state
from .service_host import HostBoundService
from .shared import (
    HTTPException,
    _read_json_dict,
    _cancel_node_work,
    _set_node_config_last_message,
    _touch_node_config_last_run_at,
    _update_node_config_state,
    _write_json_dict,
    envelope_preview,
    envelope_text,
    normalize_envelope,
)
from .node_memory_store import current_node_memory_paths
from .node_memory_store import delete_node_memory_record
from .node_memory_store import load_latest_node_memory_turn
from .node_memory_store import load_recent_node_memory_records
from .node_memory_markdown import render_memory_markdown
from .node_memory_store import read_node_memory_text


def _memory_role(record: dict) -> str:
    return str(record.get("role") or "").strip().lower()


def _select_latest_turn_records(records: list[dict], history_mode: str) -> list[dict]:
    final_assistant_index = -1
    for index in range(len(records) - 1, -1, -1):
        if _memory_role(records[index]) in {"assistant", "agent"}:
            final_assistant_index = index
            break

    visible: list[dict] = []
    for index, record in enumerate(records):
        role = _memory_role(record)
        if role in {"user", "human"} or index == final_assistant_index:
            visible.append(record)
            continue
        if history_mode == "latest_turn_progress" and (final_assistant_index < 0 or index < final_assistant_index):
            visible.append(record)
            continue
        if history_mode == "latest_turn_metadata" and final_assistant_index >= 0 and index > final_assistant_index:
            visible.append(record)
    return visible


class NodeInstanceRuntime(HostBoundService):
    def _control_clock_node(self, config_path: str, cfg: dict, action: str) -> dict:
        interval_seconds = parse_clock_interval_seconds(cfg)
        if interval_seconds <= 0:
            raise HTTPException(status_code=400, detail="clock interval must be greater than 0")

        now_ts = time.time()
        next_cfg = dict(cfg)
        next_cfg.update(build_clock_interval_fields(next_cfg))
        if action == "start":
            current_state = parse_node_state(next_cfg.get("state"))
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
        return {"ok": True, "state": parse_node_state(next_cfg.get("state")), "config": next_cfg}

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
                        if bool((current or {}).get("_delete_requested")):
                            raise HTTPException(status_code=409, detail="node is being deleted")
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

    def get_node_instance_memory(
        self,
        node_id: str,
        max_chars: int | None = 20000,
        graph_id: str = "",
        messages_limit: int | None = 400,
        history_mode: str = "recent",
    ):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._resolve_existing_node_id(safe_graph_id, node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        memory_path = self.graph_runtime._node_memory_path(safe_node_id, safe_graph_id)
        messages_path = self.graph_runtime._node_messages_path(safe_node_id, safe_graph_id)
        return self.get_node_instance_memory_from_paths(
            config_path,
            memory_path,
            messages_path,
            safe_graph_id,
            safe_node_id,
            max_chars=max_chars,
            messages_limit=messages_limit,
            history_mode=history_mode,
        )

    def get_node_instance_memory_from_paths(
        self,
        config_path: str,
        memory_path: str,
        messages_path: str,
        graph_id: str,
        node_id: str,
        max_chars: int | None = 20000,
        messages_limit: int | None = 400,
        history_mode: str = "recent",
    ):
        cfg = _read_json_dict(config_path) if isinstance(config_path, str) and config_path and os.path.exists(config_path) else {}
        if not isinstance(cfg, dict) or not cfg:
            raise HTTPException(status_code=404, detail="node instance not found")
        if bool(cfg.get("_delete_requested")):
            raise HTTPException(status_code=409, detail="node is being deleted")
        safe_history_mode = str(history_mode or "recent").strip().lower()
        lazy_turn_modes = {"latest_turn", "latest_turn_progress", "latest_turn_metadata"}
        if safe_history_mode not in {"recent", "all", *lazy_turn_modes}:
            raise HTTPException(
                status_code=400,
                detail=(
                    "history_mode must be 'recent', 'all', 'latest_turn', "
                    "'latest_turn_progress', or 'latest_turn_metadata'"
                ),
            )
        if safe_history_mode in lazy_turn_modes:
            latest_turn_records, history_complete = load_latest_node_memory_turn(memory_path, messages_path)
            records = _select_latest_turn_records(latest_turn_records, safe_history_mode)
            text = render_memory_markdown(records)
            if max_chars is not None:
                text = text[-max(0, int(max_chars)):]
        else:
            effective_limit = None if safe_history_mode == "all" else messages_limit
            records = load_recent_node_memory_records(memory_path, messages_path, limit=effective_limit)
            history_complete = effective_limit is None or len(records) < max(0, int(effective_limit))
            text = read_node_memory_text(memory_path, messages_path, max_chars=max_chars)
        messages = [normalize_envelope(item, default_role="assistant") for item in records]
        current_paths = current_node_memory_paths(memory_path, messages_path)
        live = self.core.node_live_outputs.get(graph_id, node_id) or {}
        return {
            "memory_path": current_paths.get("memory_path") or memory_path,
            "messages_path": current_paths.get("messages_path") or messages_path,
            "text": text,
            "messages": messages,
            "history_complete": history_complete,
            "latest_turn_progress_loaded": safe_history_mode in {"all", "recent", "latest_turn_progress"},
            "latest_turn_metadata_loaded": safe_history_mode in {"all", "recent", "latest_turn_metadata"},
            "state": parse_node_state(cfg.get("state")) if isinstance(cfg, dict) else "idle",
            "last_message": str(cfg.get("last_message") or "") if isinstance(cfg, dict) else "",
            "live_message": str(live.get("text") or ""),
            "thinking_message": str(live.get("thinking_text") or ""),
        }

    def delete_node_instance_memory_message(self, node_id: str, message_id: str, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._resolve_existing_node_id(safe_graph_id, node_id)
        return self.delete_node_instance_memory_message_from_paths(
            self.graph_runtime._node_config_path(safe_node_id, safe_graph_id),
            self.graph_runtime._node_memory_path(safe_node_id, safe_graph_id),
            self.graph_runtime._node_messages_path(safe_node_id, safe_graph_id),
            safe_graph_id,
            safe_node_id,
            message_id,
        )

    def delete_node_instance_memory_message_from_paths(
        self,
        config_path: str,
        memory_path: str,
        messages_path: str,
        graph_id: str,
        node_id: str,
        message_id: str,
    ):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        safe_message_id = str(message_id or "").strip()
        if not safe_message_id:
            raise HTTPException(status_code=400, detail="message id is required")
        cfg = _read_json_dict(config_path) if isinstance(config_path, str) and config_path and os.path.exists(config_path) else {}
        if not isinstance(cfg, dict) or not cfg:
            raise HTTPException(status_code=404, detail="node instance not found")
        if bool(cfg.get("_delete_requested")):
            raise HTTPException(status_code=409, detail="node is being deleted")
        result = delete_node_memory_record(memory_path, messages_path, safe_message_id)
        return {"ok": True, "deleted": int((result or {}).get("deleted") or 0), "message_id": safe_message_id}

    def get_node_instance_live(self, node_id: str, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._resolve_existing_node_id(safe_graph_id, node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        cfg = _read_json_dict(config_path) if isinstance(config_path, str) and config_path and os.path.exists(config_path) else {}
        if not isinstance(cfg, dict) or not cfg:
            raise HTTPException(status_code=404, detail="node instance not found")
        if bool(cfg.get("_delete_requested")):
            raise HTTPException(status_code=409, detail="node is being deleted")
        live = self.core.node_live_outputs.get(safe_graph_id, safe_node_id) or {}
        return {
            "node_id": safe_node_id,
            "graph_id": safe_graph_id,
            "live_message": str(live.get("text") or ""),
            "thinking_message": str(live.get("thinking_text") or ""),
        }

    def stream_node_instance_live(self, node_id: str, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._resolve_existing_node_id(safe_graph_id, node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        cfg = _read_json_dict(config_path) if isinstance(config_path, str) and config_path and os.path.exists(config_path) else {}
        if not isinstance(cfg, dict) or not cfg:
            raise HTTPException(status_code=404, detail="node instance not found")
        if bool(cfg.get("_delete_requested")):
            raise HTTPException(status_code=409, detail="node is being deleted")

        def encode_event(item: dict) -> str:
            payload = {
                "node_id": safe_node_id,
                "graph_id": safe_graph_id,
                "live_message": str((item or {}).get("text") or ""),
                "thinking_message": str((item or {}).get("thinking_text") or ""),
                "version": int((item or {}).get("version") or 0),
                "trace_id": str((item or {}).get("trace_id") or ""),
                "updated_at": float((item or {}).get("updated_at") or 0),
                "is_streaming": bool((item or {}).get("is_streaming")),
                "event_type": str((item or {}).get("event_type") or ""),
                "event": (item or {}).get("event") if isinstance((item or {}).get("event"), dict) else None,
                "interactive_session_id": str((item or {}).get("interactive_session_id") or ""),
            }
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        def events():
            item = self.core.node_live_outputs.get(safe_graph_id, safe_node_id)
            last_version = int((item or {}).get("version") or 0)
            yield encode_event(item or {"version": last_version, "text": "", "is_streaming": False})
            while True:
                item = self.core.node_live_outputs.wait_for_change(safe_graph_id, safe_node_id, last_version, timeout=15.0)
                version = int((item or {}).get("version") or 0)
                if version <= last_version:
                    yield ": keep-alive\n\n"
                    continue
                last_version = version
                yield encode_event(item)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def set_node_instance_state(self, node_id: str, payload: dict, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._resolve_existing_node_id(safe_graph_id, node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        if not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")
        current = _read_json_dict(config_path)
        if bool((current or {}).get("_delete_requested")):
            raise HTTPException(status_code=409, detail="node is being deleted")
        mapped = parse_node_state((payload or {}).get("state"))
        _update_node_config_state(config_path, mapped)
        self.graph_runtime._log_graph_event(safe_graph_id, "node_state_set", node_id=safe_node_id, state=mapped)
        if mapped == "idle":
            self.graph_runtime._ensure_graph_runner(safe_graph_id)
            self.graph_runtime._wake_graph_runner(safe_graph_id)
        return {"ok": True, "state": mapped}

    def control_node_instance(self, node_id: str, payload: dict, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._resolve_existing_node_id(safe_graph_id, node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        if not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")
        cfg = _read_json_dict(config_path)
        payload = payload if isinstance(payload, dict) else {}
        if not isinstance(cfg, dict) or not cfg:
            raise HTTPException(status_code=404, detail="node instance not found")
        if bool(cfg.get("_delete_requested")):
            raise HTTPException(status_code=409, detail="node is being deleted")

        action = str((payload or {}).get("action") or "").strip().lower()
        type_id = str(cfg.get("type_id") or "").strip()
        if type_id == "channel_receiver_node":
            return call_channel_http(self.core.channel_service.control_receiver, safe_graph_id, safe_node_id, payload)
        if type_id == "console_command_node" and action == "send_input":
            # 处理控制台命令节点交互式输入
            session_id = str((payload or {}).get("session_id") or "").strip()
            text = str((payload or {}).get("text") or "")
            send_eof = bool((payload or {}).get("send_eof"))
            send_ctrl_c = bool((payload or {}).get("send_ctrl_c"))
            append_newline = bool((payload or {}).get("append_newline"))
            ok = send_console_interactive_input(
                session_id,
                text,
                send_eof=send_eof,
                send_ctrl_c=send_ctrl_c,
                append_newline=append_newline,
            )
            if not ok:
                raise HTTPException(status_code=404, detail="interactive session not found or process exited")
            return {"ok": True}
        if type_id != "clock_node" and action == "stop":
            result = _cancel_node_work(config_path)
            active_cancelled = self.core.node_cancellations.request(config_path)
            self.graph_runtime._log_graph_event(
                safe_graph_id,
                "node_control",
                node_id=safe_node_id,
                node_type_id=type_id or None,
                action="stop",
                state=str(result.get("state") or "idle"),
                cleared_pending=int(result.get("cleared_pending") or 0),
                cleared_inflight=bool(result.get("cleared_inflight")),
                active_cancelled=active_cancelled,
            )
            result["active_cancelled"] = active_cancelled
            return {"ok": True, "state": parse_node_state(result.get("state")), "cancelled": result}
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
            self.graph_runtime._refresh_scheduled_node(safe_graph_id, safe_node_id)
        elif action == "stop":
            self.graph_runtime._unregister_scheduled_node(safe_graph_id, safe_node_id)
        return {"ok": True, "state": result.get("state")}
