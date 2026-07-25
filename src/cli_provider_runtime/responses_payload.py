from __future__ import annotations

# Canonical request serialization for the Responses API.
from typing import Any

from .contracts import CanonicalRequest
from .contracts import CodexProtocolError


def canonical_request_to_responses(request: CanonicalRequest) -> dict[str, Any]:
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []
    for message in request.messages:
        if message.role == "system":
            instructions.append(_plain_text(message.content))
            continue
        if message.role == "tool":
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
                    "output": _plain_text(message.content),
                }
            )
            continue
        if message.content:
            input_items.append(
                {
                    "type": "message",
                    "role": message.role,
                    "content": _responses_content(
                        message.content,
                        output=message.role == "assistant",
                    ),
                }
            )
        for call in message.tool_calls:
            input_items.append(
                {
                    "type": "function_call",
                    "call_id": call.call_id,
                    "name": call.wire_name,
                    "arguments": call.arguments,
                }
            )
    payload: dict[str, Any] = {
        "model": request.model,
        "input": input_items,
        "stream": request.stream,
    }
    if instructions:
        payload["instructions"] = "\n\n".join(value for value in instructions if value)
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "name": tool.wire_name,
                "description": tool.description,
                "parameters": tool.input_schema,
            }
            for tool in request.tools
        ]
        payload["tool_choice"] = _responses_tool_choice(request.tool_choice)
        payload["parallel_tool_calls"] = request.parallel_tool_calls
    if request.reasoning_effort:
        payload["reasoning"] = {"effort": request.reasoning_effort}
    if request.max_output_tokens is not None:
        payload["max_output_tokens"] = request.max_output_tokens
    return payload


def _responses_tool_choice(raw: object) -> object:
    if isinstance(raw, dict) and str(raw.get("type") or "") == "function":
        return {"type": "function", "name": str(raw.get("name") or "")}
    return raw


def _responses_content(
    raw: str | list[dict[str, Any]],
    *,
    output: bool,
) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        return [{"type": "output_text" if output else "input_text", "text": raw}]
    content: list[dict[str, Any]] = []
    for part in raw:
        part_type = str(part.get("type") or "")
        if part_type == "text":
            content.append(
                {
                    "type": "output_text" if output else "input_text",
                    "text": str(part.get("text") or ""),
                }
            )
        elif part_type == "image_url" and not output:
            image_url = part.get("image_url")
            url = str(image_url.get("url") or "") if isinstance(image_url, dict) else ""
            content.append({"type": "input_image", "image_url": url})
        else:
            raise CodexProtocolError(
                f"Unsupported canonical content part for Responses: {part_type or '<empty>'}."
            )
    return content


def _plain_text(raw: str | list[dict[str, Any]]) -> str:
    if isinstance(raw, str):
        return raw
    return "".join(
        str(part.get("text") or "")
        for part in raw
        if part.get("type") == "text"
    )


__all__ = ["canonical_request_to_responses"]
