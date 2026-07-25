from __future__ import annotations

# Projects Claude session messages into the shared session view.
import json
from datetime import datetime
from datetime import timezone
from typing import Any


def project_session_records(messages: list[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    pending_tools: dict[str, dict[str, Any]] = {}
    for message_index, session_message in enumerate(messages):
        message_type = str(getattr(session_message, "type", "") or "")
        uuid = str(getattr(session_message, "uuid", "") or f"message-{message_index}")
        raw = getattr(session_message, "message", None)
        if not isinstance(raw, dict):
            raise ValueError(f"Claude session message {uuid!r} has no message object.")
        role = str(raw.get("role") or message_type).strip()
        content = raw.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        if not isinstance(blocks, list):
            raise ValueError(f"Claude session message {uuid!r} content must be text or an array.")
        visible_parts: list[dict[str, Any]] = []
        for block_index, block in enumerate(blocks):
            if not isinstance(block, dict):
                raise ValueError(f"Claude session message {uuid!r} content block must be an object.")
            block_type = str(block.get("type") or "")
            record_id = f"claude-{uuid}-{block_index}"
            if block_type == "text":
                visible_parts.append({"type": "text", "text": str(block.get("text") or "")})
            elif block_type == "thinking":
                text = str(block.get("thinking") or "")
                if text:
                    records.append(_record(record_id, "commentary", [{"type": "text", "text": text}]))
            elif block_type == "redacted_thinking":
                records.append(
                    _record(
                        record_id,
                        "commentary",
                        [{"type": "structured", "data": dict(block)}],
                    )
                )
            elif block_type == "tool_use":
                call_id = _required_text(block.get("id"), "Claude tool_use id")
                arguments = block.get("input")
                if not isinstance(arguments, dict):
                    raise ValueError(f"Claude tool_use {call_id!r} input must be an object.")
                pending_tools[call_id] = {
                    "id": record_id,
                    "name": _required_text(block.get("name"), "Claude tool_use name"),
                    "args": dict(arguments),
                }
            elif block_type == "tool_result":
                call_id = _required_text(block.get("tool_use_id"), "Claude tool_result id")
                call = pending_tools.pop(call_id, None)
                preview = _content_preview(block.get("content"))
                records.append(
                    _record(
                        record_id,
                        "tool",
                        [
                            _tool_part(
                                call_id,
                                call=call,
                                preview=preview,
                                failed=bool(block.get("is_error")),
                            )
                        ],
                    )
                )
            else:
                records.append(
                    _record(
                        record_id,
                        "system",
                        [{"type": "structured", "data": dict(block)}],
                    )
                )
        if visible_parts:
            record_role = "assistant" if role == "assistant" else "user"
            records.append(_record(f"claude-{uuid}", record_role, visible_parts))
    for call_id, call in pending_tools.items():
        records.append(
            _record(
                str(call["id"]),
                "tool",
                [_tool_part(call_id, call=call, preview="", failed=False, status="running")],
            )
        )
    return records


def _tool_part(
    call_id: str,
    *,
    call: dict[str, Any] | None,
    preview: str,
    failed: bool,
    status: str = "",
) -> dict[str, Any]:
    normalized_status = status or ("failed" if failed else "completed")
    part: dict[str, Any] = {
        "type": "tool_call",
        "call_id": call_id,
        "name": str((call or {}).get("name") or "unknown_tool"),
        "provider": "claude",
        "status": normalized_status,
        "duration_ms": None,
        "error": preview if failed else "",
        "result_preview": preview[:4000],
        "result_chars": len(preview),
        "result_preview_truncated": len(preview) > 4000,
        "args": dict((call or {}).get("args") or {}),
    }
    return part


def _record(record_id: str, role: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": record_id,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "role": role,
        "parts": parts,
    }


def _content_preview(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        texts: list[str] = []
        for item in raw:
            if isinstance(item, dict) and str(item.get("type") or "") == "text":
                texts.append(str(item.get("text") or ""))
            else:
                texts.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
        return "\n".join(texts)
    return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))


def _required_text(raw: object, owner: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"{owner} is required.")
    return value


__all__ = ["project_session_records"]
