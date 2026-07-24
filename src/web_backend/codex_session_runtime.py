from __future__ import annotations

from datetime import datetime
from datetime import timezone
import json
import os

from src.codex_runtime.app_server_client import CodexAppServerError
from src.codex_runtime.session_manager import CodexSessionManager
from src.codex_runtime.thread_projection import project_thread_records
from src.codex_runtime.thread_state import THREAD_STATE_FILENAME
from src.codex_runtime.thread_state import read_selected_thread_id
from src.codex_runtime.thread_state import session_runtime_key
from src.codex_runtime.thread_state import write_selected_thread_id

from .node_memory_store import replace_node_memory_records
from .node_state_machine import parse_node_state
from .service_host import HostBoundService
from .shared import HTTPException
from .shared import _read_json_dict


class CodexSessionRuntime(HostBoundService):
    def list_codex_sessions(self, node_id: str, graph_id: str = "") -> dict:
        target = self._target(node_id, graph_id, require_codex=False)
        if not target["supported"]:
            return {
                "supported": False,
                "node_id": target["node_id"],
                "graph_id": target["graph_id"],
                "active_session_id": "",
                "is_new_session": True,
                "sessions": [],
            }
        try:
            threads = CodexSessionManager.instance().list_threads(target["command"])
            active_thread_id = read_selected_thread_id(target["state_path"])
        except (CodexAppServerError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        sessions = [_thread_summary(thread) for thread in threads]
        if active_thread_id and all(item["id"] != active_thread_id for item in sessions):
            try:
                active_thread = CodexSessionManager.instance().read_thread(
                    target["command"],
                    active_thread_id,
                )
            except (CodexAppServerError, RuntimeError, ValueError) as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            sessions.insert(0, _thread_summary(active_thread))
        return {
            "supported": True,
            "node_id": target["node_id"],
            "graph_id": target["graph_id"],
            "active_session_id": active_thread_id,
            "is_new_session": not bool(active_thread_id),
            "sessions": sessions,
        }

    def select_codex_session(self, node_id: str, payload: dict, graph_id: str = "") -> dict:
        target = self._target(node_id, graph_id, require_codex=True)
        config = _read_json_dict(target["config_path"])
        if parse_node_state(config.get("state")) == "working":
            raise HTTPException(status_code=409, detail="Cannot switch Codex Session while the node is working.")
        raw_session_id = (payload or {}).get("session_id") if isinstance(payload, dict) else None
        if raw_session_id is None:
            raise HTTPException(status_code=400, detail="session_id is required; use an empty string for New Session.")
        session_id = str(raw_session_id or "").strip()
        runtime_key = session_runtime_key(
            target["graph_id"],
            target["node_id"],
            target["state_path"],
        )
        records: list[dict] = []
        if session_id:
            try:
                thread = CodexSessionManager.instance().read_thread(target["command"], session_id)
                records = project_thread_records(thread)
            except (CodexAppServerError, RuntimeError, TypeError, ValueError) as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        CodexSessionManager.instance().close_session(runtime_key)
        try:
            replace_node_memory_records(
                target["memory_path"],
                target["messages_path"],
                records,
            )
            write_selected_thread_id(target["state_path"], session_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to select Codex thread: {exc}") from exc
        self.core.node_live_outputs.clear(target["graph_id"], target["node_id"])
        return {"ok": True, **self.list_codex_sessions(target["node_id"], target["graph_id"])}

    def _target(self, node_id: str, graph_id: str, *, require_codex: bool) -> dict:
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._resolve_existing_node_id(safe_graph_id, node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        config = _read_json_dict(config_path)
        supported = str(config.get("type_id") or "").strip() == "codex_node"
        if require_codex and not supported:
            raise HTTPException(status_code=400, detail=f"Node {safe_node_id!r} is not a Codex node.")
        return {
            "supported": supported,
            "node_id": safe_node_id,
            "graph_id": safe_graph_id,
            "config_path": config_path,
            "node_directory": os.path.dirname(config_path),
            "state_path": os.path.join(os.path.dirname(config_path), THREAD_STATE_FILENAME),
            "memory_path": self.graph_runtime._node_memory_path(safe_node_id, safe_graph_id),
            "messages_path": self.graph_runtime._node_messages_path(safe_node_id, safe_graph_id),
            "command": str(config.get("codex_command") or "codex").strip() or "codex",
        }


def _thread_summary(thread: object) -> dict:
    if not isinstance(thread, dict):
        raise ValueError("Codex thread/list entry must be an object.")
    thread_id = str(thread.get("id") or "").strip()
    if not thread_id:
        raise ValueError("Codex thread/list entry has no id.")
    preview = " ".join(str(thread.get("preview") or "").split())
    name = " ".join(str(thread.get("name") or "").split())
    source = thread.get("source")
    source_text = source if isinstance(source, str) else json.dumps(source, ensure_ascii=False, separators=(",", ":"))
    return {
        "id": thread_id,
        "title": name or preview or thread_id,
        "preview": preview,
        "created_at": _timestamp(thread.get("createdAt")),
        "updated_at": _timestamp(thread.get("updatedAt")),
        "cwd": str(thread.get("cwd") or ""),
        "source": source_text,
        "model_provider": str(thread.get("modelProvider") or ""),
    }


def _timestamp(value: object) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return ""
    return datetime.fromtimestamp(float(value), timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = ["CodexSessionRuntime"]
