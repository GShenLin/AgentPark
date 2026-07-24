from __future__ import annotations

import base64
import json
import urllib.parse
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


class GeminiGenerateContentAdapter:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)
        self._tools_by_wire = {}

    def complete(self, request: CanonicalRequest) -> CanonicalResult:
        response = open_json_request(
            url=self._url(request.model, stream=False),
            headers={},
            payload=self._payload(request),
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
        response = open_json_request(
            url=self._url(request.model, stream=True),
            headers={},
            payload=self._payload(request),
            policy=resolve_upstream_request_policy(self.config),
            stream=True,
        )
        yield stream_created(response_id)
        for data in iter_sse_data(response):
            if not data:
                continue
            event = _json_object(data)
            usage = event.get("usageMetadata")
            if isinstance(usage, dict):
                _apply_usage(result, usage)
            for part in _candidate_parts(event):
                if isinstance(part.get("text"), str) and part["text"]:
                    text = part["text"]
                    if part.get("thought") is True:
                        for chunk in reasoning.feed(text):
                            yield chunk
                        continue
                    for chunk in reasoning.finish():
                        yield chunk
                    if not message_started:
                        yield stream_item_added(message_item(message_id))
                        message_started = True
                    result.text += text
                    yield stream_text_delta(text)
                function_call = part.get("functionCall")
                if isinstance(function_call, dict):
                    result.tool_calls.append(self._tool_call(function_call))

        for chunk in reasoning.finish():
            yield chunk
        if message_started:
            yield stream_item_done(message_item(message_id, result.text, status="completed"))
        for call in result.tool_calls:
            yield stream_item_done(tool_call_item(call))
        yield stream_completed(result)

    def _payload(self, request: CanonicalRequest) -> dict[str, Any]:
        self._tools_by_wire = {tool.wire_name: tool for tool in request.tools}
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        call_names: dict[str, str] = {}
        for message in request.messages:
            if message.role == "system":
                system_parts.append(_plain_text(message.content))
                continue
            if message.tool_calls:
                for call in message.tool_calls:
                    call_names[call.call_id] = call.wire_name
            contents.append(self._content(message, call_names))
        payload: dict[str, Any] = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        if request.tools:
            payload["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": tool.wire_name,
                            "description": tool.description,
                            "parameters": tool.input_schema,
                        }
                        for tool in request.tools
                    ]
                }
            ]
            payload["toolConfig"] = {
                "functionCallingConfig": _tool_choice(flatten_tool_choice(request.tool_choice, request.tools))
            }
        generation: dict[str, Any] = {}
        if request.max_output_tokens is not None:
            generation["maxOutputTokens"] = request.max_output_tokens
        if generation:
            payload["generationConfig"] = generation
        return payload

    def _content(self, message: CanonicalMessage, call_names: dict[str, str]) -> dict[str, Any]:
        if message.role == "tool":
            name = message.tool_name or call_names.get(message.tool_call_id, "")
            if not name:
                raise CodexProtocolError(
                    f"Gemini tool result {message.tool_call_id!r} cannot be matched to a function name."
                )
            return {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": name,
                            "response": {"result": _plain_text(message.content)},
                        }
                    }
                ],
            }
        parts = _gemini_parts(message.content)
        for call in message.tool_calls:
            parts.append({"functionCall": {"name": call.wire_name, "args": _tool_input(call)}})
        return {"role": "model" if message.role == "assistant" else "user", "parts": parts}

    def _result(self, payload: dict[str, Any]) -> CanonicalResult:
        result = CanonicalResult(response_id=f"resp_agentpark_{uuid.uuid4().hex}")
        for part in _candidate_parts(payload):
            if isinstance(part.get("text"), str):
                result.text += part["text"]
            function_call = part.get("functionCall")
            if isinstance(function_call, dict):
                result.tool_calls.append(self._tool_call(function_call))
        usage = payload.get("usageMetadata")
        if isinstance(usage, dict):
            _apply_usage(result, usage)
        return result

    def _tool_call(self, raw: dict[str, Any]) -> CanonicalToolCall:
        name = str(raw.get("name") or "").strip()
        if not name:
            raise CodexProtocolError("Gemini returned a functionCall without a name.")
        args = raw.get("args")
        if not isinstance(args, dict):
            raise CodexProtocolError(f"Gemini functionCall {name!r} args must be an object.")
        tool = self._tools_by_wire.get(name)
        if tool is None:
            raise CodexProtocolError(f"Provider returned undeclared tool call {name!r}.")
        kind = tool.kind
        if kind == "custom":
            if not isinstance(args.get("input"), str):
                raise CodexProtocolError(f"Custom tool {name!r} must return an object containing string field 'input'.")
            arguments = args["input"]
        else:
            arguments = json.dumps(args, ensure_ascii=False, separators=(",", ":"))
        return CanonicalToolCall(
            call_id=f"call_{uuid.uuid4().hex}",
            name=tool.name,
            arguments=arguments,
            kind=kind,
            namespace=tool.namespace,
        )

    def _url(self, model: str, *, stream: bool) -> str:
        base_url = str(self.config.get("baseUrl") or "").rstrip("/")
        if not base_url:
            raise ValueError("Provider baseUrl is required.")
        method = "streamGenerateContent" if stream else "generateContent"
        path = f"{base_url}/models/{urllib.parse.quote(model, safe='')}:{method}"
        query = {"key": str(self.config.get("apiKey") or "")}
        if stream:
            query["alt"] = "sse"
        if not query["key"]:
            raise ValueError("Gemini provider apiKey is required.")
        return f"{path}?{urllib.parse.urlencode(query)}"


def _gemini_parts(raw: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        return [{"text": raw}]
    parts: list[dict[str, Any]] = []
    for part in raw:
        part_type = str(part.get("type") or "")
        if part_type == "text":
            parts.append({"text": str(part.get("text") or "")})
            continue
        if part_type != "image_url":
            raise CodexProtocolError(f"Unsupported Gemini content part: {part_type or '<empty>'}")
        image_url = part.get("image_url")
        url = str(image_url.get("url") or "") if isinstance(image_url, dict) else ""
        if not url.startswith("data:") or ";base64," not in url:
            raise CodexProtocolError("Gemini image conversion requires a base64 data URL.")
        header, encoded = url.split(",", 1)
        mime_type = header[5:].split(";", 1)[0]
        try:
            base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise CodexProtocolError("Gemini image data URL contains invalid base64.") from exc
        parts.append({"inlineData": {"mimeType": mime_type, "data": encoded}})
    return parts


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


def _tool_choice(raw: object) -> dict[str, Any]:
    if raw is None or raw == "auto":
        return {"mode": "AUTO"}
    if raw == "none":
        return {"mode": "NONE"}
    if raw == "required":
        return {"mode": "ANY"}
    if isinstance(raw, dict) and str(raw.get("type") or "") in {"function", "custom"}:
        name = str(raw.get("name") or "").strip()
        if name:
            return {"mode": "ANY", "allowedFunctionNames": [name]}
    raise CodexProtocolError(f"Unsupported Gemini tool_choice: {raw!r}")


def _candidate_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return []
    parts: list[dict[str, Any]] = []
    for candidate in candidates:
        content = candidate.get("content") if isinstance(candidate, dict) else None
        raw_parts = content.get("parts") if isinstance(content, dict) else None
        if isinstance(raw_parts, list):
            parts.extend(part for part in raw_parts if isinstance(part, dict))
    return parts


def _json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CodexProtocolError("Gemini SSE data is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise CodexProtocolError("Gemini SSE data must be an object.")
    return value


def _apply_usage(result: CanonicalResult, usage: dict[str, Any]) -> None:
    result.input_tokens = _count(usage.get("promptTokenCount"))
    result.output_tokens = _count(usage.get("candidatesTokenCount"))


def _count(raw: Any) -> int:
    return int(raw) if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else 0
