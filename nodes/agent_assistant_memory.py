from __future__ import annotations

from typing import Any

from src.web_backend.node_memory_store import append_node_memory_entry


def persist_assistant_tool_call_note(
    *,
    message: Any,
    memory_path: str,
    messages_path: str,
) -> bool:
    if not _is_visible_assistant_tool_call_note(message):
        return False
    append_node_memory_entry(memory_path, messages_path, "assistant", message)
    return True


def _is_visible_assistant_tool_call_note(message: Any) -> bool:
    if not isinstance(message, dict):
        return False
    if str(message.get("role") or "").strip().lower() != "assistant":
        return False
    if not isinstance(message.get("tool_calls"), list) or not message.get("tool_calls"):
        return False
    content = message.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if not isinstance(content, list):
        return False
    for part in content:
        if not isinstance(part, dict):
            continue
        text = str(part.get("text") or "").strip()
        if text:
            return True
    return False
