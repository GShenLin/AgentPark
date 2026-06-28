from __future__ import annotations

import os
from typing import Any

from .companion_capabilities import infer_node_can
from .node_config_service import node_config_service
from .node_event_sequence import read_node_event_seq
from .node_state_machine import parse_node_state


LAST_MESSAGE_TRUNCATION_HINT_CHARS = 10000


class CompanionNodeSummarizer:
    def __init__(self, core: object) -> None:
        self.core = core

    def read_node_summary(self, graph_id: str, node_id: str) -> dict[str, Any]:
        config_path = self.core.graph_runtime._node_config_path(node_id, graph_id)
        if not config_path or not os.path.exists(config_path):
            raise ValueError(f"node instance not found: {graph_id}/{node_id}")
        cfg = node_config_service.read_strict(config_path)
        cfg["_config_version"] = self._config_version(config_path)
        return self.enrich_node_summary(graph_id, cfg)

    def enrich_node_summary(self, graph_id: str, item: dict[str, Any]) -> dict[str, Any]:
        payload = dict(item)
        node_id = str(payload.get("node_id") or "").strip()
        payload["graph_id"] = self.core.graph_runtime._sanitize_graph_id(payload.get("graph_id") or graph_id)
        payload["state"] = parse_node_state(payload.get("state"))
        pending = payload.get("pending")
        payload["pending_count"] = len(pending) if isinstance(pending, list) else int(payload.get("pending_count") or 0)
        payload["inflight"] = payload.get("inflight") if isinstance(payload.get("inflight"), dict) else None
        payload["live_message"] = ""
        if node_id:
            live = self.core.node_live_outputs.get(payload["graph_id"], node_id) or {}
            payload["live_message"] = str(live.get("text") or "")
        payload["node_event_seq"] = read_node_event_seq(payload)
        payload["message_id"] = str(payload["node_event_seq"])
        payload["message_version"] = int(payload["node_event_seq"])
        payload["last_error"] = last_error(payload)
        payload["capabilities"] = capabilities(payload)
        payload["completed_requests"] = completed_requests(payload)
        payload["last_completed_request"] = payload["completed_requests"][-1] if payload["completed_requests"] else None
        payload["last_message_truncated"] = last_message_truncated(payload)
        if payload["last_message_truncated"]:
            payload["memory_hint"] = {"tool": "get_node_memory", "max_chars": 20000}
        return payload

    def node_status_payload(self, graph_id: str, item: dict[str, Any]) -> dict[str, Any]:
        payload = self.enrich_node_summary(graph_id, item)
        return {
            "graph_id": str(payload.get("graph_id") or graph_id),
            "node_id": str(payload.get("node_id") or ""),
            "type_id": str(payload.get("type_id") or ""),
            "name": str(payload.get("name") or payload.get("node_id") or ""),
            "state": parse_node_state(payload.get("state")),
            "pending_count": int(payload.get("pending_count") or 0),
            "has_inflight": isinstance(payload.get("inflight"), dict),
            "stop_requested": bool(payload.get("_stop_requested")),
            "working_path": str((payload.get("capabilities") or {}).get("working_path") or ""),
            "last_message": str(payload.get("last_message") or ""),
            "last_message_truncated": bool(payload.get("last_message_truncated")),
            "memory_hint": payload.get("memory_hint"),
            "live_message": str(payload.get("live_message") or ""),
            "last_run_at": str(payload.get("last_run_at") or ""),
            "last_error": payload.get("last_error"),
            "last_completed_request": payload.get("last_completed_request"),
            "message_id": str(payload.get("message_id") or ""),
            "message_version": int(payload.get("message_version") or 0),
            "node_event_seq": int(payload.get("node_event_seq") or 0),
            "can": (payload.get("capabilities") or {}).get("can") or {},
            "capabilities": payload.get("capabilities") or {},
        }

    @staticmethod
    def is_node_idle(payload: dict[str, Any]) -> bool:
        return (
            parse_node_state(payload.get("state")) == "idle"
            and int(payload.get("pending_count") or 0) == 0
            and not isinstance(payload.get("inflight"), dict)
        )

    @staticmethod
    def _config_version(config_path: str) -> int:
        try:
            return int(os.stat(config_path).st_mtime_ns)
        except OSError:
            return 0


def capabilities(payload: dict[str, Any]) -> dict[str, Any]:
    exact = {
        "tools": _string_list(payload.get("tools")),
        "mcp_servers": _string_list(payload.get("mcp_servers")),
        "skills": _string_list(payload.get("skills")),
        "plugins": _string_list(payload.get("plugins")),
        "working_path": str(payload.get("working_path") or ""),
        "provider": str(payload.get("provider") or payload.get("model") or ""),
        "model": str(payload.get("model") or ""),
    }
    exact["can"] = infer_node_can(exact)
    return exact


def last_error(payload: dict[str, Any]) -> dict[str, Any] | None:
    event = payload.get("last_runtime_event")
    if isinstance(event, dict):
        error = str(event.get("error") or "").strip()
        if error:
            return {"source": "runtime_event", "message": error}
    calls = payload.get("runtime_tool_calls")
    if isinstance(calls, list):
        for call in reversed(calls):
            if not isinstance(call, dict):
                continue
            error = str(call.get("error") or "").strip()
            if error:
                return {
                    "source": "tool_call",
                    "tool": str(call.get("name") or ""),
                    "message": error,
                }
    last_message = str(payload.get("last_message") or "").strip()
    if last_message.startswith("Error:"):
        return {"source": "last_message", "message": last_message}
    return None


def last_message_truncated(payload: dict[str, Any]) -> bool:
    message = str(payload.get("last_message") or "")
    if len(message) >= LAST_MESSAGE_TRUNCATION_HINT_CHARS:
        return True
    if message.rstrip().endswith(("...", "\u2026", "[truncated]", "<truncated>")):
        return True
    calls = payload.get("runtime_tool_calls")
    if isinstance(calls, list):
        return any(
            isinstance(call, dict)
            and (
                bool(call.get("result_preview_truncated"))
                or bool(call.get("result_tail_preview_truncated"))
            )
            for call in calls
        )
    return False


def completed_requests(payload: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    history = payload.get("completed_requests")
    if isinstance(history, list):
        for item in history[-20:]:
            if not isinstance(item, dict):
                continue
            output.append(_request_record(item))
    last = payload.get("last_completed_request")
    if isinstance(last, dict):
        record = _request_record(last)
        request_id = str(record.get("request_id") or "")
        if request_id and not any(str(item.get("request_id") or "") == request_id for item in output):
            output.append(record)
    return output[-20:]


def _request_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": str(item.get("request_id") or item.get("trace_id") or ""),
        "trace_id": str(item.get("trace_id") or item.get("request_id") or ""),
        "role": str(item.get("role") or "assistant"),
        "message": str(item.get("message") or ""),
        "state": parse_node_state(item.get("state")),
        "node_event_seq": int(item.get("node_event_seq") or 0),
        "completed_at": str(item.get("completed_at") or ""),
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


__all__ = ["CompanionNodeSummarizer"]
