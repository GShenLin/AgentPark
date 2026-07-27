from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable
from typing import Any

from .contracts import CanonicalResult
from .contracts import CanonicalToolCall
from .contracts import CodexProtocolError


def canonical_result_to_chat(result: CanonicalResult, *, model: str) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": result.text or None}
    if result.tool_calls:
        message["tool_calls"] = [_tool_call(call) for call in result.tool_calls]
    return {
        "id": _completion_id(result.response_id),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": "tool_calls" if result.tool_calls else "stop",
            }
        ],
        "usage": {
            "prompt_tokens": result.input_tokens,
            "completion_tokens": result.output_tokens,
            "total_tokens": result.total_tokens,
        },
    }


def responses_sse_to_chat(chunks: Iterable[bytes], *, model: str) -> Iterable[bytes]:
    completion_id = f"chatcmpl-agentpark-{uuid.uuid4().hex}"
    created = int(time.time())
    started = False
    saw_tool = False
    tool_index = 0
    usage: dict[str, int] | None = None

    def frame(delta: dict[str, Any], finish_reason: str | None = None) -> bytes:
        payload: dict[str, Any] = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        if usage is not None and finish_reason is not None:
            payload["usage"] = usage
        return _data(payload)

    for chunk in chunks:
        event = _responses_event(chunk)
        if event is None:
            continue
        event_type = str(event.get("type") or "")
        if event_type == "response.created":
            response = event.get("response")
            response_id = str(response.get("id") or "") if isinstance(response, dict) else ""
            if response_id:
                completion_id = _completion_id(response_id)
            if not started:
                started = True
                yield frame({"role": "assistant", "content": ""})
            continue
        if not started:
            started = True
            yield frame({"role": "assistant", "content": ""})
        if event_type == "response.output_text.delta":
            delta = str(event.get("delta") or "")
            if delta:
                yield frame({"content": delta})
        elif event_type == "response.output_item.done":
            item = event.get("item")
            if isinstance(item, dict) and str(item.get("type") or "") in {
                "function_call",
                "custom_tool_call",
            }:
                call = _item_tool_call(item)
                saw_tool = True
                yield frame(
                    {
                        "tool_calls": [
                            {
                                "index": tool_index,
                                "id": call["id"],
                                "type": "function",
                                "function": call["function"],
                            }
                        ]
                    }
                )
                tool_index += 1
        elif event_type == "response.completed":
            response = event.get("response")
            raw_usage = response.get("usage") if isinstance(response, dict) else None
            if isinstance(raw_usage, dict):
                prompt = _count(raw_usage.get("input_tokens"))
                completion = _count(raw_usage.get("output_tokens"))
                usage = {
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_tokens": prompt + completion,
                }
        elif event_type == "response.failed":
            response = event.get("response")
            error = response.get("error") if isinstance(response, dict) else None
            message = str(error.get("message") or error) if isinstance(error, dict) else str(error or "Provider failed.")
            yield _data({"error": {"message": message, "type": "agentpark_gateway_error"}})
            yield b"data: [DONE]\n\n"
            return
    if not started:
        yield frame({"role": "assistant", "content": ""})
    yield frame({}, "tool_calls" if saw_tool else "stop")
    yield b"data: [DONE]\n\n"


def _responses_event(chunk: bytes) -> dict[str, Any] | None:
    data_lines = [
        line.strip()[5:].lstrip()
        for line in bytes(chunk).splitlines()
        if line.strip().startswith(b"data:")
    ]
    if not data_lines or b"\n".join(data_lines) == b"[DONE]":
        return None
    try:
        value = json.loads(b"\n".join(data_lines).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CodexProtocolError("Responses stream frame is not valid UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise CodexProtocolError("Responses stream event must be an object.")
    return value


def _tool_call(call: CanonicalToolCall) -> dict[str, Any]:
    arguments = (
        json.dumps({"input": call.arguments}, ensure_ascii=False, separators=(",", ":"))
        if call.kind == "custom"
        else call.arguments
    )
    return {
        "id": call.call_id,
        "type": "function",
        "function": {"name": call.wire_name, "arguments": arguments},
    }


def _item_tool_call(item: dict[str, Any]) -> dict[str, Any]:
    call_id = str(item.get("call_id") or item.get("id") or "").strip()
    name = str(item.get("name") or "").strip()
    if not call_id or not name:
        raise CodexProtocolError("Responses tool call requires call_id and name.")
    item_type = str(item.get("type") or "")
    arguments = (
        json.dumps({"input": str(item.get("input") or "")}, ensure_ascii=False, separators=(",", ":"))
        if item_type == "custom_tool_call"
        else str(item.get("arguments") or "{}")
    )
    return {"id": call_id, "function": {"name": name, "arguments": arguments}}


def _completion_id(response_id: str) -> str:
    value = str(response_id or "").strip()
    return value if value.startswith("chatcmpl-") else f"chatcmpl-agentpark-{uuid.uuid4().hex}"


def _count(value: Any) -> int:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _data(payload: dict[str, Any]) -> bytes:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"data: {body}\n\n".encode("utf-8")


__all__ = ["canonical_result_to_chat", "responses_sse_to_chat"]
