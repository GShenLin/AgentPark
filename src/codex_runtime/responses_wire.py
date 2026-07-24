from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from typing import Any

from .contracts import CanonicalResult
from .contracts import CanonicalToolCall
from .contracts import CodexProtocolError


def canonical_result_to_response(result: CanonicalResult, *, model: str) -> dict[str, Any]:
    output = _result_output_items(result)
    return {
        "id": result.response_id,
        "object": "response",
        "status": "completed",
        "model": model,
        "output": output,
        "output_text": result.text,
        "usage": _usage(result),
    }


def canonical_result_sse(result: CanonicalResult) -> Iterable[bytes]:
    yield _sse("response.created", {"type": "response.created", "response": {"id": result.response_id}})
    for item in _result_output_items(result):
        yield _sse("response.output_item.done", {"type": "response.output_item.done", "item": item})
    yield _sse(
        "response.completed",
        {"type": "response.completed", "response": {"id": result.response_id, "usage": _usage(result)}},
    )


def stream_created(response_id: str) -> bytes:
    return _sse("response.created", {"type": "response.created", "response": {"id": response_id}})


def stream_text_delta(delta: str) -> bytes:
    return _sse("response.output_text.delta", {"type": "response.output_text.delta", "delta": delta})


def stream_reasoning_part_added(item_id: str) -> bytes:
    return _sse(
        "response.reasoning_summary_part.added",
        {
            "type": "response.reasoning_summary_part.added",
            "item_id": item_id,
            "summary_index": 0,
        },
    )


def stream_reasoning_delta(item_id: str, delta: str) -> bytes:
    return _sse(
        "response.reasoning_summary_text.delta",
        {
            "type": "response.reasoning_summary_text.delta",
            "item_id": item_id,
            "summary_index": 0,
            "delta": delta,
        },
    )


def stream_reasoning_done(item_id: str, text: str) -> bytes:
    return _sse(
        "response.reasoning_summary_text.done",
        {
            "type": "response.reasoning_summary_text.done",
            "item_id": item_id,
            "summary_index": 0,
            "text": text,
        },
    )


def stream_item_added(item: dict[str, Any]) -> bytes:
    return _sse("response.output_item.added", {"type": "response.output_item.added", "item": item})


def stream_item_done(item: dict[str, Any]) -> bytes:
    return _sse("response.output_item.done", {"type": "response.output_item.done", "item": item})


def stream_completed(result: CanonicalResult) -> bytes:
    return _sse(
        "response.completed",
        {"type": "response.completed", "response": {"id": result.response_id, "usage": _usage(result)}},
    )


def stream_failed(response_id: str, message: str) -> bytes:
    return _sse(
        "response.failed",
        {
            "type": "response.failed",
            "response": {
                "id": response_id,
                "status": "failed",
                "error": {"code": "agentpark_provider_error", "message": str(message)},
            },
        },
    )


def message_item(item_id: str, text: str = "", *, status: str = "in_progress") -> dict[str, Any]:
    return {
        "type": "message",
        "role": "assistant",
        "id": item_id,
        "status": status,
        "content": [{"type": "output_text", "text": text}],
    }


def reasoning_item(item_id: str, text: str = "") -> dict[str, Any]:
    summary = [{"type": "summary_text", "text": text}] if text else []
    return {
        "type": "reasoning",
        "id": item_id,
        "summary": summary,
        "encrypted_content": None,
    }


def tool_call_item(call: CanonicalToolCall) -> dict[str, Any]:
    item_id = f"fc_{uuid.uuid4().hex}"
    if call.kind == "custom":
        return {
            "type": "custom_tool_call",
            "id": item_id,
            "call_id": call.call_id,
            "name": call.name,
            "input": call.arguments,
        }
    if call.kind == "tool_search":
        return {
            "type": "tool_search_call",
            "id": item_id,
            "call_id": call.call_id,
            "status": "completed",
            "execution": "client",
            "arguments": _decoded_json_object(call.arguments, "tool_search call arguments"),
        }
    item = {
        "type": "function_call",
        "id": item_id,
        "call_id": call.call_id,
        "name": call.name,
        "arguments": call.arguments,
        "status": "completed",
    }
    if call.namespace:
        item["namespace"] = call.namespace
    return item


def _result_output_items(result: CanonicalResult) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    if result.text:
        output.append(message_item(f"msg_{uuid.uuid4().hex}", result.text, status="completed"))
    output.extend(tool_call_item(call) for call in result.tool_calls)
    return output


def _usage(result: CanonicalResult) -> dict[str, Any]:
    return {
        "input_tokens": result.input_tokens,
        "input_tokens_details": None,
        "output_tokens": result.output_tokens,
        "output_tokens_details": None,
        "total_tokens": result.total_tokens,
    }


def _sse(event: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {body}\n\n".encode("utf-8")


def _decoded_json_object(raw: str, owner: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CodexProtocolError(f"{owner} must be valid JSON.") from exc
    if not isinstance(value, dict):
        raise CodexProtocolError(f"{owner} must decode to an object.")
    return value
