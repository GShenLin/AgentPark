from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from typing import Any

from src.cli_provider_runtime.contracts import CanonicalResult
from src.cli_provider_runtime.contracts import CanonicalToolCall
from src.cli_provider_runtime.contracts import CodexProtocolError


def canonical_result_to_message(result: CanonicalResult, *, model: str) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    if result.text:
        content.append({"type": "text", "text": result.text})
    content.extend(_tool_block(call) for call in result.tool_calls)
    return {
        "id": _message_id(result.response_id),
        "type": "message",
        "role": "assistant",
        "content": content,
        "model": model,
        "stop_reason": "tool_use" if result.tool_calls else "end_turn",
        "stop_sequence": None,
        "usage": _usage(result),
    }


def responses_sse_to_messages(
    chunks: Iterable[bytes],
    *,
    model: str,
) -> Iterable[bytes]:
    message_id = f"msg_agentpark_{uuid.uuid4().hex}"
    input_tokens = 0
    output_tokens = 0
    text_started = False
    text_index = 0
    next_index = 0
    saw_tool = False
    started = False

    def start_message() -> bytes:
        nonlocal started
        started = True
        return _sse(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": message_id,
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": model,
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": input_tokens, "output_tokens": 0},
                },
            },
        )

    for chunk in chunks:
        event = _responses_event(chunk)
        if event is None:
            continue
        event_type = str(event.get("type") or "")
        if event_type == "response.created":
            if not started:
                yield start_message()
            continue
        if event_type == "response.output_text.delta":
            if not started:
                yield start_message()
            if not text_started:
                text_started = True
                text_index = next_index
                next_index += 1
                yield _sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": text_index,
                        "content_block": {"type": "text", "text": ""},
                    },
                )
            delta = str(event.get("delta") or "")
            if delta:
                yield _sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": text_index,
                        "delta": {"type": "text_delta", "text": delta},
                    },
                )
            continue
        if event_type == "response.output_item.done":
            item = event.get("item")
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "")
            if item_type == "message":
                if text_started:
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    raise CodexProtocolError("Responses message output item must have a content array.")
                fallback_text = "".join(
                    str(part.get("text") or "")
                    for part in content
                    if isinstance(part, dict)
                    and str(part.get("type") or "") in {"output_text", "text"}
                )
                if fallback_text:
                    if not started:
                        yield start_message()
                    text_started = True
                    text_index = next_index
                    next_index += 1
                    yield _sse(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": text_index,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                    yield _sse(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": text_index,
                            "delta": {"type": "text_delta", "text": fallback_text},
                        },
                    )
                continue
            if item_type not in {
                "function_call",
                "custom_tool_call",
            }:
                continue
            if not started:
                yield start_message()
            if text_started:
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_index})
                text_started = False
            call = _tool_call(item)
            index = next_index
            next_index += 1
            saw_tool = True
            yield _sse(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {
                        "type": "tool_use",
                        "id": call.call_id,
                        "name": call.name,
                        "input": {},
                    },
                },
            )
            yield _sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "input_json_delta", "partial_json": call.arguments},
                },
            )
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": index})
            continue
        if event_type == "response.completed":
            response = event.get("response")
            usage = response.get("usage") if isinstance(response, dict) else None
            if isinstance(usage, dict):
                input_tokens = _count(usage.get("input_tokens"))
                output_tokens = _count(usage.get("output_tokens"))
            continue
        if event_type == "response.failed":
            response = event.get("response")
            error = response.get("error") if isinstance(response, dict) else None
            message = str(error.get("message") or error) if isinstance(error, dict) else str(error or "Provider failed.")
            yield _sse("error", {"type": "error", "error": {"type": "api_error", "message": message}})
            return

    if not started:
        yield start_message()
    if text_started:
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": text_index})
    yield _sse(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {
                "stop_reason": "tool_use" if saw_tool else "end_turn",
                "stop_sequence": None,
            },
            "usage": {"output_tokens": output_tokens},
        },
    )
    yield _sse("message_stop", {"type": "message_stop"})


def _responses_event(chunk: bytes) -> dict[str, Any] | None:
    data_lines: list[bytes] = []
    for raw_line in bytes(chunk).splitlines():
        line = raw_line.strip()
        if line.startswith(b"data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return None
    raw = b"\n".join(data_lines)
    if raw == b"[DONE]":
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexProtocolError("Responses stream frame is not valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise CodexProtocolError("Responses stream event must be an object.")
    return value


def _tool_call(item: dict[str, Any]) -> CanonicalToolCall:
    item_type = str(item.get("type") or "")
    call_id = str(item.get("call_id") or item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    if not call_id or not name:
        raise CodexProtocolError("Responses tool call requires call_id and name.")
    if item_type == "custom_tool_call":
        arguments = json.dumps(
            {"input": str(item.get("input") or "")},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    else:
        arguments = str(item.get("arguments") or "{}")
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise CodexProtocolError(f"Responses tool call {name!r} arguments are invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise CodexProtocolError(f"Responses tool call {name!r} arguments must decode to an object.")
    return CanonicalToolCall(
        call_id=call_id,
        name=name,
        arguments=json.dumps(parsed, ensure_ascii=False, separators=(",", ":")),
    )


def _tool_block(call: CanonicalToolCall) -> dict[str, Any]:
    try:
        value = json.loads(call.arguments)
    except json.JSONDecodeError as exc:
        raise CodexProtocolError(f"Tool call {call.name!r} arguments are invalid JSON.") from exc
    if not isinstance(value, dict):
        raise CodexProtocolError(f"Tool call {call.name!r} arguments must decode to an object.")
    return {"type": "tool_use", "id": call.call_id, "name": call.name, "input": value}


def _message_id(response_id: str) -> str:
    value = str(response_id or "").strip()
    return value if value.startswith("msg_") else f"msg_agentpark_{uuid.uuid4().hex}"


def _usage(result: CanonicalResult) -> dict[str, int]:
    return {"input_tokens": result.input_tokens, "output_tokens": result.output_tokens}


def _count(raw: Any) -> int:
    return int(raw) if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else 0


def _sse(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


__all__ = ["canonical_result_to_message", "responses_sse_to_messages"]
