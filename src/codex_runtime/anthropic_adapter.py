from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Iterable
from typing import Any

from .contracts import CanonicalMessage
from .contracts import CanonicalRequest
from .contracts import CanonicalResult
from .contracts import CanonicalToolCall
from .contracts import CodexProtocolError
from .http_transport import iter_sse_data
from .http_transport import open_json_request
from .http_transport import read_json_response
from .http_transport import resolve_upstream_request_policy
from .provider_adapter import flatten_tool_choice
from .responses_conversion import message_item
from .responses_conversion import stream_completed
from .responses_conversion import stream_created
from .responses_conversion import stream_item_added
from .responses_conversion import stream_item_done
from .responses_conversion import stream_text_delta
from .responses_conversion import tool_call_item
from .responses_reasoning import ResponsesReasoningStream


class AnthropicMessagesAdapter:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)
        self._tools_by_wire = {}

    def complete(self, request: CanonicalRequest) -> CanonicalResult:
        response = open_json_request(
            url=self._url(),
            headers=self._headers(),
            payload=self._payload(request, stream=False),
            policy=resolve_upstream_request_policy(self.config),
            stream=False,
        )
        return self._result(read_json_response(response))

    def stream(self, request: CanonicalRequest, *, response_id: str = "") -> Iterable[bytes]:
        response_id = str(response_id or "").strip() or f"resp_agentpark_{uuid.uuid4().hex}"
        result = CanonicalResult(response_id=response_id)
        message_id = f"msg_{uuid.uuid4().hex}"
        message_started = False
        reasoning = ResponsesReasoningStream()
        blocks: dict[int, dict[str, Any]] = {}
        response = open_json_request(
            url=self._url(),
            headers=self._headers(),
            payload=self._payload(request, stream=True),
            policy=resolve_upstream_request_policy(self.config),
            stream=True,
        )
        yield stream_created(response_id)
        for data in iter_sse_data(response):
            if not data:
                continue
            event = _json_object(data)
            event_type = str(event.get("type") or "")
            if event_type == "message_start":
                message = event.get("message")
                if isinstance(message, dict):
                    usage = message.get("usage")
                    if isinstance(usage, dict):
                        result.input_tokens = _count(usage.get("input_tokens"))
                continue
            if event_type == "content_block_start":
                index = _index(event)
                block = event.get("content_block")
                if not isinstance(block, dict):
                    raise CodexProtocolError("Anthropic content_block_start has no content_block object.")
                blocks[index] = {
                    "type": str(block.get("type") or ""),
                    "id": str(block.get("id") or ""),
                    "name": str(block.get("name") or ""),
                    "text": str(block.get("text") or ""),
                    "json": "",
                    "input": block.get("input"),
                }
                if str(block.get("type") or "") == "thinking":
                    for chunk in reasoning.feed(str(block.get("thinking") or "")):
                        yield chunk
                continue
            if event_type == "content_block_delta":
                index = _index(event)
                state = blocks.setdefault(index, {"type": "", "id": "", "name": "", "text": "", "json": ""})
                delta = event.get("delta")
                if not isinstance(delta, dict):
                    continue
                delta_type = str(delta.get("type") or "")
                if delta_type == "text_delta":
                    text = str(delta.get("text") or "")
                    if text:
                        for chunk in reasoning.finish():
                            yield chunk
                        if not message_started:
                            yield stream_item_added(message_item(message_id))
                            message_started = True
                        state["text"] = str(state.get("text") or "") + text
                        result.text += text
                        yield stream_text_delta(text)
                elif delta_type == "thinking_delta":
                    for chunk in reasoning.feed(str(delta.get("thinking") or "")):
                        yield chunk
                elif delta_type == "input_json_delta":
                    state["json"] = str(state.get("json") or "") + str(delta.get("partial_json") or "")
                continue
            if event_type == "message_delta":
                usage = event.get("usage")
                if isinstance(usage, dict):
                    result.output_tokens = _count(usage.get("output_tokens"))

        for chunk in reasoning.finish():
            yield chunk
        if message_started:
            yield stream_item_done(message_item(message_id, result.text, status="completed"))
        result.tool_calls = [self._tool_call(state) for _, state in sorted(blocks.items()) if state.get("type") == "tool_use"]
        for call in result.tool_calls:
            yield stream_item_done(tool_call_item(call))
        yield stream_completed(result)

    def _payload(self, request: CanonicalRequest, *, stream: bool) -> dict[str, Any]:
        self._tools_by_wire = {tool.wire_name: tool for tool in request.tools}
        system_parts: list[str] = []
        messages: list[dict[str, Any]] = []
        for message in request.messages:
            if message.role == "system":
                system_parts.append(_plain_text(message.content))
                continue
            messages.append(self._message(message))
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_output_tokens or 8192,
            "stream": stream,
        }
        if system_parts:
            payload["system"] = "\n\n".join(part for part in system_parts if part)
        if request.tools:
            payload["tools"] = [
                {"name": tool.wire_name, "description": tool.description, "input_schema": tool.input_schema}
                for tool in request.tools
            ]
            payload["tool_choice"] = _tool_choice(
                flatten_tool_choice(request.tool_choice, request.tools),
                request.parallel_tool_calls,
            )
        return payload

    def _message(self, message: CanonicalMessage) -> dict[str, Any]:
        if message.role == "tool":
            return {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": message.tool_call_id, "content": _plain_text(message.content)}
                ],
            }
        content: list[dict[str, Any]] = _anthropic_content(message.content)
        for call in message.tool_calls:
            content.append(
                {
                    "type": "tool_use",
                    "id": call.call_id,
                    "name": call.wire_name,
                    "input": _tool_input(call),
                }
            )
        return {"role": "assistant" if message.role == "assistant" else "user", "content": content}

    def _result(self, payload: dict[str, Any]) -> CanonicalResult:
        result = CanonicalResult(response_id=str(payload.get("id") or f"resp_agentpark_{uuid.uuid4().hex}"))
        content = payload.get("content")
        if not isinstance(content, list):
            raise CodexProtocolError("Anthropic response content must be an array.")
        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "")
            if block_type == "text":
                result.text += str(block.get("text") or "")
            elif block_type == "tool_use":
                result.tool_calls.append(self._tool_call(block))
        usage = payload.get("usage")
        if isinstance(usage, dict):
            result.input_tokens = _count(usage.get("input_tokens"))
            result.output_tokens = _count(usage.get("output_tokens"))
        return result

    def _tool_call(self, raw: dict[str, Any]) -> CanonicalToolCall:
        name = str(raw.get("name") or "").strip()
        if not name:
            raise CodexProtocolError("Anthropic returned a tool call without a name.")
        call_id = str(raw.get("id") or f"call_{uuid.uuid4().hex}")
        encoded = str(raw.get("json") or "")
        input_value = raw.get("input")
        if encoded:
            try:
                input_value = json.loads(encoded)
            except json.JSONDecodeError as exc:
                raise CodexProtocolError(f"Anthropic tool {name!r} returned invalid JSON input.") from exc
        elif input_value is None:
            input_value = {}
        tool = self._tools_by_wire.get(name)
        if tool is None:
            raise CodexProtocolError(f"Provider returned undeclared tool call {name!r}.")
        kind = tool.kind
        if kind == "custom":
            if not isinstance(input_value, dict) or not isinstance(input_value.get("input"), str):
                raise CodexProtocolError(f"Custom tool {name!r} must return an object containing string field 'input'.")
            arguments = input_value["input"]
        else:
            arguments = json.dumps(input_value, ensure_ascii=False, separators=(",", ":"))
        return CanonicalToolCall(
            call_id=call_id,
            name=tool.name,
            arguments=arguments,
            kind=kind,
            namespace=tool.namespace,
        )

    def _url(self) -> str:
        base_url = str(self.config.get("baseUrl") or "").rstrip("/")
        if not base_url:
            raise ValueError("Provider baseUrl is required.")
        return base_url if base_url.endswith("/messages") else f"{base_url}/messages"

    def _headers(self) -> dict[str, str]:
        api_key = str(self.config.get("apiKey") or "")
        if not api_key:
            raise ValueError("Anthropic provider apiKey is required.")
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}


def _anthropic_content(raw: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        return [{"type": "text", "text": raw}]
    output: list[dict[str, Any]] = []
    for part in raw:
        part_type = str(part.get("type") or "")
        if part_type == "text":
            output.append({"type": "text", "text": str(part.get("text") or "")})
        elif part_type == "image_url":
            image_url = part.get("image_url")
            url = str(image_url.get("url") or "") if isinstance(image_url, dict) else ""
            if not url:
                raise CodexProtocolError("Anthropic image content requires a URL.")
            if url.startswith("data:") and ";base64," in url:
                header, encoded = url.split(",", 1)
                media_type = header[5:].split(";", 1)[0]
                try:
                    base64.b64decode(encoded, validate=True)
                except ValueError as exc:
                    raise CodexProtocolError("Anthropic image data URL contains invalid base64.") from exc
                output.append(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": encoded},
                    }
                )
            else:
                output.append({"type": "image", "source": {"type": "url", "url": url}})
        else:
            raise CodexProtocolError(f"Unsupported Anthropic content part: {part_type or '<empty>'}")
    return output


def _plain_text(raw: str | list[dict[str, Any]]) -> str:
    if isinstance(raw, str):
        return raw
    return "".join(str(part.get("text") or "") for part in raw if part.get("type") == "text")


def _tool_input(call: CanonicalToolCall) -> dict[str, Any]:
    if call.kind == "custom":
        return {"input": call.arguments}
    try:
        value = json.loads(call.arguments)
    except json.JSONDecodeError as exc:
        raise CodexProtocolError(f"Function tool {call.name!r} arguments are not valid JSON.") from exc
    if not isinstance(value, dict):
        raise CodexProtocolError(f"Function tool {call.name!r} arguments must decode to an object.")
    return value


def _tool_choice(raw: object, parallel: bool) -> dict[str, Any]:
    disable_parallel = not parallel
    if raw is None or raw == "auto":
        return {"type": "auto", "disable_parallel_tool_use": disable_parallel}
    if raw == "none":
        return {"type": "none"}
    if raw == "required":
        return {"type": "any", "disable_parallel_tool_use": disable_parallel}
    if isinstance(raw, dict) and str(raw.get("type") or "") in {"function", "custom"}:
        name = str(raw.get("name") or "").strip()
        if name:
            return {"type": "tool", "name": name, "disable_parallel_tool_use": disable_parallel}
    raise CodexProtocolError(f"Unsupported Anthropic tool_choice: {raw!r}")


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CodexProtocolError("Anthropic SSE data is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise CodexProtocolError("Anthropic SSE data must be an object.")
    return value


def _index(event: dict[str, Any]) -> int:
    value = event.get("index")
    if not isinstance(value, int) or isinstance(value, bool):
        raise CodexProtocolError("Anthropic SSE content block index must be an integer.")
    return value


def _count(raw: Any) -> int:
    return int(raw) if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else 0
