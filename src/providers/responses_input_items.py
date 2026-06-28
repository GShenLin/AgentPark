from __future__ import annotations

from typing import Any

from src.tool.tool_call_protocol import ensure_json_text


def build_responses_message_input_item(
    *,
    role: str,
    content: list[dict[str, Any]],
    status: str = "",
) -> dict[str, Any]:
    return {
        "type": "message",
        "role": str(role or "").strip(),
        "content": content,
        "status": str(status or "completed").strip() or "completed",
    }


def build_responses_function_call_input_item(
    *,
    call_id: str,
    name: str,
    arguments: Any,
    item_id: str = "",
    status: str = "",
) -> dict[str, Any]:
    item = {
        "type": "function_call",
        "call_id": call_id,
        "name": name,
        "arguments": ensure_json_text(arguments),
        "status": str(status or "completed").strip() or "completed",
    }
    if item_id:
        item["id"] = item_id
    return item


def build_responses_function_call_output_item(call_id: str, output: Any) -> dict[str, Any]:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": ensure_json_text(output),
        "status": "completed",
    }


def with_completed_input_status(item: dict[str, Any]) -> dict[str, Any]:
    next_item = dict(item)
    next_item["status"] = str(next_item.get("status") or "completed").strip() or "completed"
    return next_item
