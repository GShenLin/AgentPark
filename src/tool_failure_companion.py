from __future__ import annotations

import os
from typing import Any

from src.companion_inbox import deliver_companion_notice
from src.companion_notice_settings import companion_tool_failure_memory_enabled
from src.operational_memory_notice_context import build_operational_memory_notice_context


TOOL_FAILURE_RESULT_PREVIEW_CHARS = 1600
RECENT_MESSAGE_PREVIEW_CHARS = 600
RECENT_MESSAGE_LIMIT = 8


def notify_companion_about_tool_failure_memory(
    agent: object,
    failures: list[dict[str, Any]],
) -> bool:
    if not companion_tool_failure_memory_enabled():
        return False
    notice = build_tool_failure_memory_notice(agent, failures)
    if _is_companion_self_notice(notice):
        return False
    return deliver_companion_notice(notice, delivery_enabled=True)


def build_tool_failure_memory_notice(agent: object, failures: list[dict[str, Any]]) -> dict[str, Any]:
    from src.providers.agent_runtime_context import get_agent_runtime_context

    context = get_agent_runtime_context(agent)
    memory_path = str(getattr(agent, "current_memory_path", "") or "").strip()
    memory_context = build_operational_memory_notice_context(memory_path=memory_path)
    node_dir = os.path.dirname(os.path.abspath(memory_path)) if memory_path else ""
    failure = _first_failure(failures)
    return {
        "type": "tool_failure_memory_notice",
        "source": {
            "graph_id": context.graph_id,
            "node_id": context.node_id,
            "node_type_id": context.node_type_id or "agent_node",
            "provider": str(getattr(agent, "provider_name", "") or "").strip(),
        },
        "run": {
            "trace_id": "",
        },
        "failure": failure,
        "memory": memory_context,
        "context": {
            "workspace_root": context.workspace_root,
            "working_path": context.working_path,
            "collaboration_mode": context.collaboration_mode,
            "shell": context.shell,
            "recent_messages": _recent_message_previews(getattr(agent, "messages", None)),
        },
        "report": {
            "memory_path": memory_path,
            "messages_path": os.path.join(node_dir, "messages.jsonl") if node_dir else "",
            "runtime_events_path": os.path.join(node_dir, "runtime_events.jsonl") if node_dir else "",
        },
    }


def _first_failure(failures: list[dict[str, Any]]) -> dict[str, Any]:
    first = failures[0] if failures else {}
    if not isinstance(first, dict):
        first = {}
    return {
        "tool_name": str(first.get("tool_name") or "").strip(),
        "call_id": str(first.get("call_id") or "").strip(),
        "status": str(first.get("status") or "").strip(),
        "error": str(first.get("error") or "").strip(),
        "result_preview": _truncate(first.get("result_preview"), TOOL_FAILURE_RESULT_PREVIEW_CHARS),
        "failure_count": len(failures),
    }


def _recent_message_previews(messages: object) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for message in list(messages or [])[-RECENT_MESSAGE_LIMIT:] if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip()
        content = message.get("content")
        text = _content_preview(content)
        if not text:
            continue
        output.append({"role": role, "text": _truncate(text, RECENT_MESSAGE_PREVIEW_CHARS)})
    return output


def _content_preview(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or item.get("name") or item.get("type")
                if text:
                    parts.append(str(text))
            elif item is not None:
                parts.append(str(item))
        return " ".join(part.strip() for part in parts if part.strip()).strip()
    if isinstance(content, dict):
        for key in ("text", "content", "message"):
            value = content.get(key)
            if value:
                return str(value).strip()
    return str(content or "").strip()


def _truncate(value: object, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _is_companion_self_notice(notice: dict[str, Any]) -> bool:
    source = notice.get("source") if isinstance(notice, dict) else None
    if not isinstance(source, dict):
        return False
    graph_id = str(source.get("graph_id") or "").strip()
    node_id = str(source.get("node_id") or "").strip()
    return graph_id == "companion" and node_id == "companion"


__all__ = [
    "build_tool_failure_memory_notice",
    "notify_companion_about_tool_failure_memory",
]
