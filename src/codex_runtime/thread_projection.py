from __future__ import annotations

import json
from datetime import datetime
from datetime import timezone
from typing import Any


_TOOL_ITEM_TYPES = {
    "commandExecution",
    "fileChange",
    "mcpToolCall",
    "dynamicToolCall",
    "collabAgentToolCall",
    "webSearch",
    "imageView",
    "sleep",
    "imageGeneration",
}


def project_thread_records(thread: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(thread, dict):
        raise TypeError("Codex thread projection requires a thread object.")
    thread_id = str(thread.get("id") or "").strip()
    if not thread_id:
        raise ValueError("Codex thread projection requires a thread id.")
    turns = thread.get("turns")
    if not isinstance(turns, list):
        raise ValueError(f"Codex thread {thread_id!r} has no turns array.")

    records: list[dict[str, Any]] = []
    for turn_index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            raise ValueError(f"Codex thread {thread_id!r} turn {turn_index} is not an object.")
        turn_id = str(turn.get("id") or f"turn-{turn_index}").strip() or f"turn-{turn_index}"
        items = turn.get("items")
        if not isinstance(items, list):
            raise ValueError(f"Codex thread {thread_id!r} turn {turn_id!r} has no items array.")
        created_at = _turn_timestamp(turn)
        for item_index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(
                    f"Codex thread {thread_id!r} turn {turn_id!r} item {item_index} is not an object."
                )
            record = _project_item(
                item,
                thread_id=thread_id,
                turn_id=turn_id,
                item_index=item_index,
                created_at=created_at,
            )
            if record is not None:
                records.append(record)
    return records


def _project_item(
    item: dict[str, Any],
    *,
    thread_id: str,
    turn_id: str,
    item_index: int,
    created_at: str,
) -> dict[str, Any] | None:
    item_type = str(item.get("type") or "").strip()
    item_id = str(item.get("id") or f"{turn_id}-{item_index}").strip() or f"{turn_id}-{item_index}"
    base = {
        "id": f"codex-{item_id}",
        "created_at": created_at,
    }
    if item_type == "userMessage":
        return {
            **base,
            "role": "user",
            "parts": _user_parts(item.get("content")),
        }
    if item_type == "agentMessage":
        return {
            **base,
            "role": "assistant",
            "parts": [{"type": "text", "text": str(item.get("text") or "")}],
        }
    if item_type in {"reasoning", "plan"}:
        text = _reasoning_text(item)
        if not text:
            return None
        return {
            **base,
            "role": "commentary",
            "parts": [{"type": "text", "text": text}],
        }
    if item_type in _TOOL_ITEM_TYPES:
        return {
            **base,
            "role": "tool",
            "parts": [_tool_part(item, thread_id=thread_id)],
        }
    if item_type == "hookPrompt":
        return {
            **base,
            "role": "system",
            "parts": [{"type": "structured", "data": dict(item)}],
        }
    return {
        **base,
        "role": "system",
        "parts": [{"type": "structured", "data": dict(item)}],
    }


def _user_parts(content: object) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        raise ValueError("Codex userMessage content must be an array.")
    parts: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            raise ValueError("Codex userMessage content item must be an object.")
        item_type = str(item.get("type") or "").strip()
        if item_type == "text":
            parts.append({"type": "text", "text": str(item.get("text") or "")})
        elif item_type == "image":
            parts.append(_resource_part(str(item.get("url") or ""), source="codex"))
        elif item_type == "localImage":
            parts.append(_resource_part(str(item.get("path") or ""), source="codex"))
        else:
            parts.append({"type": "structured", "data": dict(item)})
    return parts


def _resource_part(uri: str, *, source: str) -> dict[str, Any]:
    return {
        "type": "resource",
        "resource": {
            "uri": uri,
            "kind": "image",
            "source": source,
        },
    }


def _reasoning_text(item: dict[str, Any]) -> str:
    if str(item.get("type") or "") == "plan":
        return str(item.get("text") or "").strip()
    blocks: list[str] = []
    for field in ("summary", "content"):
        value = item.get(field)
        if isinstance(value, list):
            blocks.extend(str(block or "").strip() for block in value if str(block or "").strip())
    return "\n\n".join(dict.fromkeys(blocks))


def _tool_part(item: dict[str, Any], *, thread_id: str) -> dict[str, Any]:
    call_id = str(item.get("id") or "").strip() or f"{thread_id}-{item.get('type')}"
    preview = _tool_result_preview(item)
    part: dict[str, Any] = {
        "type": "tool_call",
        "call_id": call_id,
        "name": _tool_name(item),
        "provider": "codex",
        "status": _tool_status(item),
        "duration_ms": item.get("durationMs"),
        "error": _tool_error(item),
        "result_preview": preview[:4000],
        "result_chars": len(preview),
        "result_preview_truncated": len(preview) > 4000,
        "args": _tool_arguments(item),
    }
    return part


def _tool_name(item: dict[str, Any]) -> str:
    item_type = str(item.get("type") or "")
    if item_type == "commandExecution":
        return "shell_command"
    if item_type == "fileChange":
        return "apply_patch"
    if item_type == "mcpToolCall":
        return f"{str(item.get('server') or 'mcp')}.{str(item.get('tool') or 'tool')}"
    if item_type == "dynamicToolCall":
        namespace = str(item.get("namespace") or "").strip()
        tool = str(item.get("tool") or "tool").strip() or "tool"
        return f"{namespace}.{tool}" if namespace else tool
    if item_type == "collabAgentToolCall":
        return f"collaboration.{str(item.get('tool') or 'tool')}"
    return {
        "webSearch": "web_search",
        "imageView": "view_image",
        "sleep": "wait",
        "imageGeneration": "image_generation",
    }.get(item_type, item_type or "codex_tool")


def _tool_arguments(item: dict[str, Any]) -> dict[str, Any]:
    item_type = str(item.get("type") or "")
    if item_type == "commandExecution":
        return {"command": str(item.get("command") or ""), "cwd": str(item.get("cwd") or "")}
    if item_type == "fileChange":
        return {"changes": item.get("changes") if isinstance(item.get("changes"), list) else []}
    if item_type in {"mcpToolCall", "dynamicToolCall"}:
        arguments = item.get("arguments")
        return dict(arguments) if isinstance(arguments, dict) else {"value": arguments}
    if item_type == "collabAgentToolCall":
        return {
            "prompt": item.get("prompt"),
            "model": item.get("model"),
            "receiver_thread_ids": item.get("receiverThreadIds"),
        }
    if item_type == "webSearch":
        return {"query": str(item.get("query") or ""), "action": item.get("action")}
    if item_type == "imageView":
        return {"path": str(item.get("path") or "")}
    if item_type == "sleep":
        return {"duration_ms": item.get("durationMs")}
    return {}


def _tool_result_preview(item: dict[str, Any]) -> str:
    item_type = str(item.get("type") or "")
    if item_type == "commandExecution":
        return str(item.get("aggregatedOutput") or "")
    if item_type == "fileChange":
        value: object = item.get("changes")
    elif item_type == "mcpToolCall":
        value = item.get("result")
    elif item_type == "dynamicToolCall":
        value = item.get("contentItems")
    elif item_type == "collabAgentToolCall":
        value = item.get("agentsStates")
    else:
        value = item.get("action") or item.get("path") or ""
    if isinstance(value, str):
        return value
    return "" if value is None else json.dumps(value, ensure_ascii=False)


def _tool_status(item: dict[str, Any]) -> str:
    raw = str(item.get("status") or "").strip()
    return {
        "inProgress": "running",
        "completed": "completed",
        "failed": "failed",
        "declined": "declined",
    }.get(raw, raw or "completed")


def _tool_error(item: dict[str, Any]) -> str:
    raw = item.get("error")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        return str(raw.get("message") or json.dumps(raw, ensure_ascii=False))
    if _tool_status(item) in {"failed", "declined"}:
        return f"Codex tool call {item.get('status')}."
    return ""


def _turn_timestamp(turn: dict[str, Any]) -> str:
    raw = turn.get("startedAt")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        raw = turn.get("completedAt")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return datetime.fromtimestamp(float(raw), timezone.utc).isoformat().replace("+00:00", "Z")
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = ["project_thread_records"]
