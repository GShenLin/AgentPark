from __future__ import annotations

import json
import os
from datetime import datetime
from datetime import timezone
from typing import Any

from nodes.claude_node.runtime.session_manager import ClaudeSessionManager
from nodes.claude_node.runtime.session_projection import project_session_records
from nodes.claude_node.runtime.session_state import SESSION_STATE_FILENAME
from nodes.claude_node.runtime.session_state import read_selected_session_id
from nodes.claude_node.runtime.session_state import session_runtime_key as claude_runtime_key
from nodes.claude_node.runtime.session_state import write_selected_session_id
from nodes.codex_node.runtime.app_server_client import CodexAppServerError
from nodes.codex_node.runtime.session_manager import CodexSessionManager
from nodes.codex_node.runtime.thread_projection import project_thread_records
from nodes.codex_node.runtime.thread_state import THREAD_STATE_FILENAME
from nodes.codex_node.runtime.thread_state import read_selected_thread_id
from nodes.codex_node.runtime.thread_state import session_runtime_key as codex_runtime_key
from nodes.codex_node.runtime.thread_state import write_selected_thread_id
from src.workspace_settings import get_workspace_root

from .node_memory_store import replace_node_memory_records
from .node_state_machine import parse_node_state
from .service_host import HostBoundService
from .shared import HTTPException
from .shared import _read_json_dict


class CliSessionRuntime(HostBoundService):
    def list_cli_sessions(self, node_id: str, graph_id: str = "") -> dict[str, Any]:
        target = self._target(node_id, graph_id, require_supported=False)
        if not target["supported"]:
            return self._response(target, active_session_id="", sessions=[])
        try:
            active_session_id = self._read_selected(target)
            sessions = self._list(target)
            if active_session_id and all(item["id"] != active_session_id for item in sessions):
                active = self._active_summary(target, active_session_id)
                sessions.insert(0, active)
        except (CodexAppServerError, OSError, RuntimeError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return self._response(
            target,
            active_session_id=active_session_id,
            sessions=sessions,
        )

    def select_cli_session(self, node_id: str, payload: dict, graph_id: str = "") -> dict[str, Any]:
        target = self._target(node_id, graph_id, require_supported=True)
        config = _read_json_dict(target["config_path"])
        if parse_node_state(config.get("state")) == "working":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot switch {target['session_label']} Session while the node is working.",
            )
        raw_session_id = (payload or {}).get("session_id") if isinstance(payload, dict) else None
        if raw_session_id is None:
            raise HTTPException(
                status_code=400,
                detail="session_id is required; use an empty string for New Session.",
            )
        session_id = str(raw_session_id or "").strip()
        records: list[dict[str, Any]] = []
        if session_id:
            try:
                records = self._read_records(target, session_id)
            except (CodexAppServerError, OSError, RuntimeError, TypeError, ValueError) as exc:
                raise HTTPException(status_code=502, detail=str(exc)) from exc
        self._close_runtime_session(target)
        try:
            replace_node_memory_records(
                target["memory_path"],
                target["messages_path"],
                records,
            )
            self._write_selected(target, session_id)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to select {target['session_label']} Session: {exc}",
            ) from exc
        self.core.node_live_outputs.clear(target["graph_id"], target["node_id"])
        return {
            "ok": True,
            **self.list_cli_sessions(target["node_id"], target["graph_id"]),
        }

    def _list(self, target: dict[str, Any]) -> list[dict[str, Any]]:
        if target["session_kind"] == "codex":
            threads = CodexSessionManager.instance().list_threads(target["command"])
            return [_codex_summary(thread) for thread in threads]
        sessions = ClaudeSessionManager.instance().list_sessions(target["cwd"])
        return [_claude_summary(session) for session in sessions]

    def _active_summary(self, target: dict[str, Any], session_id: str) -> dict[str, Any]:
        if target["session_kind"] == "codex":
            thread = CodexSessionManager.instance().read_thread(target["command"], session_id)
            return _codex_summary(thread)
        info = ClaudeSessionManager.instance().get_session_info(target["cwd"], session_id)
        return _claude_summary(info) if info is not None else _missing_summary(session_id)

    def _read_records(self, target: dict[str, Any], session_id: str) -> list[dict[str, Any]]:
        if target["session_kind"] == "codex":
            thread = CodexSessionManager.instance().read_thread(target["command"], session_id)
            return project_thread_records(thread)
        messages = ClaudeSessionManager.instance().read_session(target["cwd"], session_id)
        return project_session_records(messages)

    def _read_selected(self, target: dict[str, Any]) -> str:
        if target["session_kind"] == "codex":
            return read_selected_thread_id(target["state_path"])
        return read_selected_session_id(target["state_path"])

    def _write_selected(self, target: dict[str, Any], session_id: str) -> None:
        if target["session_kind"] == "codex":
            write_selected_thread_id(target["state_path"], session_id)
        else:
            write_selected_session_id(target["state_path"], session_id)

    def _close_runtime_session(self, target: dict[str, Any]) -> None:
        if target["session_kind"] == "codex":
            runtime_key = codex_runtime_key(
                target["graph_id"],
                target["node_id"],
                target["state_path"],
            )
            CodexSessionManager.instance().close_session(runtime_key)
        else:
            runtime_key = claude_runtime_key(
                target["graph_id"],
                target["node_id"],
                target["state_path"],
            )
            ClaudeSessionManager.instance().close_session(runtime_key)

    def _response(
        self,
        target: dict[str, Any],
        *,
        active_session_id: str,
        sessions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "supported": target["supported"],
            "session_kind": target["session_kind"],
            "session_label": target["session_label"],
            "node_id": target["node_id"],
            "graph_id": target["graph_id"],
            "active_session_id": active_session_id,
            "is_new_session": not bool(active_session_id),
            "sessions": sessions,
        }

    def _target(
        self,
        node_id: str,
        graph_id: str,
        *,
        require_supported: bool,
    ) -> dict[str, Any]:
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._resolve_existing_node_id(safe_graph_id, node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        config = _read_json_dict(config_path)
        type_id = str(config.get("type_id") or "").strip()
        session_kind = {"codex_node": "codex", "claude_node": "claude"}.get(type_id, "")
        supported = bool(session_kind)
        if require_supported and not supported:
            raise HTTPException(
                status_code=400,
                detail=f"Node {safe_node_id!r} does not support native CLI Sessions.",
            )
        node_directory = os.path.dirname(config_path)
        cwd = (
            _working_directory(config)
            if session_kind == "claude"
            else os.path.abspath(get_workspace_root())
        )
        return {
            "supported": supported,
            "session_kind": session_kind,
            "session_label": {"codex": "Codex", "claude": "Claude"}.get(session_kind, ""),
            "node_id": safe_node_id,
            "graph_id": safe_graph_id,
            "config_path": config_path,
            "state_path": os.path.join(
                node_directory,
                THREAD_STATE_FILENAME if session_kind == "codex" else SESSION_STATE_FILENAME,
            ),
            "memory_path": self.graph_runtime._node_memory_path(safe_node_id, safe_graph_id),
            "messages_path": self.graph_runtime._node_messages_path(safe_node_id, safe_graph_id),
            "command": str(config.get("codex_command") or "codex").strip() or "codex",
            "cwd": cwd,
        }


def _codex_summary(thread: object) -> dict[str, Any]:
    if not isinstance(thread, dict):
        raise ValueError("Codex thread/list entry must be an object.")
    thread_id = str(thread.get("id") or "").strip()
    if not thread_id:
        raise ValueError("Codex thread/list entry has no id.")
    preview = " ".join(str(thread.get("preview") or "").split())
    name = " ".join(str(thread.get("name") or "").split())
    source = thread.get("source")
    source_text = source if isinstance(source, str) else json.dumps(
        source,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "id": thread_id,
        "title": name or preview or thread_id,
        "preview": preview,
        "created_at": _timestamp(thread.get("createdAt"), milliseconds=False),
        "updated_at": _timestamp(thread.get("updatedAt"), milliseconds=False),
        "cwd": str(thread.get("cwd") or ""),
        "source": source_text,
        "model_provider": str(thread.get("modelProvider") or ""),
    }


def _claude_summary(session: object) -> dict[str, Any]:
    session_id = str(getattr(session, "session_id", "") or "").strip()
    if not session_id:
        raise ValueError("Claude session entry has no session_id.")
    summary = " ".join(str(getattr(session, "summary", "") or "").split())
    title = " ".join(str(getattr(session, "custom_title", "") or "").split())
    preview = " ".join(str(getattr(session, "first_prompt", "") or summary).split())
    return {
        "id": session_id,
        "title": title or summary or preview or session_id,
        "preview": preview,
        "created_at": _timestamp(getattr(session, "created_at", None), milliseconds=True),
        "updated_at": _timestamp(getattr(session, "last_modified", None), milliseconds=True),
        "cwd": str(getattr(session, "cwd", "") or ""),
        "source": "claude-code",
        "model_provider": "",
    }


def _missing_summary(session_id: str) -> dict[str, Any]:
    return {
        "id": session_id,
        "title": session_id,
        "preview": "",
        "created_at": "",
        "updated_at": "",
        "cwd": "",
        "source": "claude-code",
        "model_provider": "",
    }


def _working_directory(config: dict[str, Any]) -> str:
    raw = str(config.get("working_path") or "").strip()
    cwd = os.path.abspath(os.path.expanduser(raw)) if raw else os.path.abspath(get_workspace_root())
    if not os.path.isdir(cwd):
        raise ValueError(f"CLI Session working_path does not exist: {cwd}")
    return cwd


def _timestamp(value: object, *, milliseconds: bool) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return ""
    seconds = float(value) / 1000.0 if milliseconds else float(value)
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = ["CliSessionRuntime"]
