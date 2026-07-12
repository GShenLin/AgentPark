from __future__ import annotations

from typing import Any

from src.web_backend.node_memory_store import append_node_memory_entry


def persist_assistant_progress(
    *,
    message: Any,
    memory_path: str,
    messages_path: str,
) -> bool:
    if not _is_assistant_progress(message):
        return False
    content = _progress_text(message.get("content"))
    tool_call_refs = _tool_call_refs(message.get("tool_calls"))
    progress_envelope = {
        "role": "assistant_progress",
        "parts": [
            {"type": "text", "text": content},
            {
                "type": "meta",
                "meta": {
                    "kind": "assistant_progress",
                    "context_policy": "exclude",
                    "tool_calls": tool_call_refs,
                },
            },
        ],
    }
    append_node_memory_entry(memory_path, messages_path, "assistant_progress", progress_envelope)
    return True


def _is_assistant_progress(message: Any) -> bool:
    if not isinstance(message, dict):
        return False
    if str(message.get("role") or "").strip().lower() != "assistant_progress":
        return False
    if str(message.get("context_policy") or "").strip().lower() != "exclude":
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


def _progress_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    texts = []
    for part in content:
        if not isinstance(part, dict):
            continue
        text = str(part.get("text") or "").strip()
        if text:
            texts.append(text)
    return "\n".join(texts)


def _tool_call_refs(tool_calls: Any) -> list[dict[str, str]]:
    refs = []
    for call in tool_calls if isinstance(tool_calls, list) else []:
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        ref = {
            "call_id": str(call.get("id") or call.get("call_id") or "").strip(),
            "name": str(function.get("name") or call.get("name") or "").strip(),
        }
        if ref["call_id"] or ref["name"]:
            refs.append(ref)
    return refs
