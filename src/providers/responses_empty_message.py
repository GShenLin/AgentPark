from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


EMPTY_MESSAGE_ERROR = "Error: EmptyMessage"
MAX_EMPTY_MESSAGE_FEEDBACK_ATTEMPTS = 1
MAX_EMPTY_MESSAGE_FIELD_CHARS = 800
MAX_EMPTY_MESSAGE_ITEMS = 8


@dataclass(frozen=True)
class EmptyMessageAction:
    kind: str
    next_input: list[Any] | None = None
    feedback_item: dict[str, Any] | None = None
    error_text: str = ""


class EmptyMessageFeedbackController:
    def __init__(self, *, max_feedback_attempts: int = MAX_EMPTY_MESSAGE_FEEDBACK_ATTEMPTS):
        self._max_feedback_attempts = max(0, int(max_feedback_attempts))
        self._feedback_count = 0

    def reset(self) -> None:
        self._feedback_count = 0

    def inspect(
        self,
        *,
        result: Any,
        content: str,
        function_calls: list[Any],
        stream_text: str,
        current_input: Any,
        explicit_context_input: list[Any],
        response_id: Any = "",
    ) -> EmptyMessageAction:
        if not is_empty_responses_message(result, content, function_calls, stream_text):
            return EmptyMessageAction("none")
        if self._feedback_count >= self._max_feedback_attempts:
            return EmptyMessageAction(
                "error",
                error_text=empty_message_final_error(
                    current_input=current_input,
                    result=result,
                    response_id=response_id,
                ),
            )
        feedback_item = build_empty_message_feedback_item(
            current_input=current_input,
            result=result,
            response_id=response_id,
        )
        self._feedback_count += 1
        return EmptyMessageAction(
            "feedback",
            next_input=[feedback_item],
            feedback_item=feedback_item,
        )


def is_empty_responses_message(result: Any, content: str, function_calls: list[Any], stream_text: str = "") -> bool:
    if str(content or "").strip():
        return False
    if str(stream_text or "").strip():
        return False
    if function_calls:
        return False
    output = result.get("output") if isinstance(result, dict) else None
    return not _has_consumable_output_item(output)


def build_empty_message_feedback_item(
    *,
    current_input: Any,
    result: Any,
    response_id: Any = "",
) -> dict[str, Any]:
    payload = {
        "error": "EmptyMessage",
        "message": (
            "The previous Responses turn returned no output_text and no function_call. "
            "Use the input and item summaries below to continue with a normal assistant message "
            "or a valid function_call."
        ),
        "response_id": str(response_id or "").strip(),
        "input": summarize_responses_items(current_input),
        "item": summarize_responses_items(result.get("output") if isinstance(result, dict) else None),
    }
    text = f"{EMPTY_MESSAGE_ERROR}\n{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
    return {"role": "user", "content": [{"type": "input_text", "text": text}]}


def empty_message_final_error(*, current_input: Any, result: Any, response_id: Any = "") -> str:
    payload = {
        "error": "EmptyMessage",
        "message": "Provider returned no output_text and no function_call after EmptyMessage feedback.",
        "response_id": str(response_id or "").strip(),
        "input": summarize_responses_items(current_input),
        "item": summarize_responses_items(result.get("output") if isinstance(result, dict) else None),
    }
    return f"{EMPTY_MESSAGE_ERROR}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}"


def summarize_responses_items(value: Any) -> dict[str, Any]:
    items = value if isinstance(value, list) else []
    output: list[dict[str, Any]] = []
    for item in items[:MAX_EMPTY_MESSAGE_ITEMS]:
        output.append(_summarize_item(item))
    return {
        "count": len(items),
        "truncated": len(items) > MAX_EMPTY_MESSAGE_ITEMS,
        "items": output,
    }


def _has_consumable_output_item(output: Any) -> bool:
    if not isinstance(output, list):
        return False
    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "function_call":
            name = str(item.get("name") or "").strip()
            call_id = str(item.get("call_id") or "").strip()
            if name and call_id:
                return True
        if item_type == "message":
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                part_type = str(part.get("type") or "").strip().lower()
                if part_type in {"output_text", "text"} and str(part.get("text") or "").strip():
                    return True
    return False


def _summarize_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"type": type(item).__name__, "preview": _preview(item)}
    item_type = str(item.get("type") or item.get("role") or "item").strip() or "item"
    summary: dict[str, Any] = {"type": item_type}
    for key in ("id", "call_id", "name", "role", "status", "text", "refusal"):
        value = item.get(key)
        if value is not None and str(value or "").strip():
            summary[key] = _preview(value, limit=160)
    content = item.get("content")
    if content is not None:
        summary["content"] = _summarize_content(content)
    arguments = item.get("arguments")
    if arguments is not None:
        summary["arguments"] = _preview(arguments)
    output = item.get("output")
    if output is not None:
        summary["output"] = _preview(output)
    return summary


def _summarize_content(content: Any) -> Any:
    if isinstance(content, list):
        return [_summarize_item(part) for part in content[:MAX_EMPTY_MESSAGE_ITEMS]]
    return _preview(content)


def _preview(value: Any, *, limit: int = MAX_EMPTY_MESSAGE_FIELD_CHARS) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            text = str(value)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
