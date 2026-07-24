from __future__ import annotations

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


class OpenAIChatAdapter:
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
        return self._result_from_json(read_json_response(response))

    def stream(self, request: CanonicalRequest, *, response_id: str = "") -> Iterable[bytes]:
        response_id = str(response_id or "").strip() or f"resp_agentpark_{uuid.uuid4().hex}"
        result = CanonicalResult(response_id=response_id)
        message_id = f"msg_{uuid.uuid4().hex}"
        message_started = False
        reasoning = ResponsesReasoningStream()
        tool_calls: dict[int, dict[str, str]] = {}
        response = open_json_request(
            url=self._url(),
            headers=self._headers(),
            payload=self._payload(request, stream=True),
            policy=resolve_upstream_request_policy(self.config),
            stream=True,
        )
        yield stream_created(response_id)
        for data in iter_sse_data(response):
            if not data or data == "[DONE]":
                continue
            event = _json_object(data, "Chat Completions SSE event")
            if isinstance(event.get("usage"), dict):
                self._apply_usage(result, event["usage"])
            choices = event.get("choices")
            if not isinstance(choices, list):
                continue
            for choice in choices:
                delta = choice.get("delta") if isinstance(choice, dict) else None
                if not isinstance(delta, dict):
                    continue
                for chunk in reasoning.feed(_chat_reasoning_delta(delta)):
                    yield chunk
                text = delta.get("content")
                if isinstance(text, str) and text:
                    for chunk in reasoning.finish():
                        yield chunk
                    if not message_started:
                        yield stream_item_added(message_item(message_id))
                        message_started = True
                    result.text += text
                    yield stream_text_delta(text)
                self._accumulate_tool_calls(tool_calls, delta.get("tool_calls"))

        for chunk in reasoning.finish():
            yield chunk
        if message_started:
            yield stream_item_done(message_item(message_id, result.text, status="completed"))
        result.tool_calls = self._finish_tool_calls(tool_calls)
        for call in result.tool_calls:
            yield stream_item_done(tool_call_item(call))
        yield stream_completed(result)

    def _payload(self, request: CanonicalRequest, *, stream: bool) -> dict[str, Any]:
        self._tools_by_wire = {tool.wire_name: tool for tool in request.tools}
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [self._message(message) for message in request.messages],
            "stream": stream,
        }
        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.wire_name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
                for tool in request.tools
            ]
            payload["tool_choice"] = _chat_tool_choice(flatten_tool_choice(request.tool_choice, request.tools))
            payload["parallel_tool_calls"] = request.parallel_tool_calls
        self._apply_reasoning(payload, request.reasoning_effort)
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _message(self, message: CanonicalMessage) -> dict[str, Any]:
        if message.role == "tool":
            return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
        output: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.tool_calls:
            output["content"] = message.content or None
            output["tool_calls"] = [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {
                        "name": call.wire_name,
                        "arguments": _chat_arguments(call),
                    },
                }
                for call in message.tool_calls
            ]
        return output

    def _result_from_json(self, payload: dict[str, Any]) -> CanonicalResult:
        response_id = str(payload.get("id") or f"resp_agentpark_{uuid.uuid4().hex}")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise CodexProtocolError("Chat Completions response has no choice.")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise CodexProtocolError("Chat Completions choice has no message object.")
        result = CanonicalResult(response_id=response_id, text=_text_content(message.get("content")))
        result.tool_calls = self._tool_calls_from_complete(message.get("tool_calls"))
        if isinstance(payload.get("usage"), dict):
            self._apply_usage(result, payload["usage"])
        return result

    def _tool_calls_from_complete(self, raw: Any) -> list[CanonicalToolCall]:
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise CodexProtocolError("Chat Completions tool_calls must be an array.")
        calls: list[CanonicalToolCall] = []
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("function"), dict):
                raise CodexProtocolError("Chat Completions tool call is malformed.")
            function = item["function"]
            calls.append(
                self._canonical_call(
                    str(item.get("id") or f"call_{uuid.uuid4().hex}"),
                    str(function.get("name") or ""),
                    str(function.get("arguments") or ""),
                )
            )
        return calls

    def _accumulate_tool_calls(self, target: dict[int, dict[str, str]], raw: Any) -> None:
        if raw is None:
            return
        if not isinstance(raw, list):
            raise CodexProtocolError("Streaming Chat Completions tool_calls must be an array.")
        for fallback_index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise CodexProtocolError("Streaming Chat Completions tool call must be an object.")
            index = item.get("index", fallback_index)
            if not isinstance(index, int) or isinstance(index, bool):
                raise CodexProtocolError("Streaming Chat Completions tool call index must be an integer.")
            state = target.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if item.get("id"):
                state["id"] = str(item["id"])
            function = item.get("function")
            if isinstance(function, dict):
                if function.get("name"):
                    state["name"] += str(function["name"])
                if function.get("arguments"):
                    state["arguments"] += str(function["arguments"])

    def _finish_tool_calls(self, raw: dict[int, dict[str, str]]) -> list[CanonicalToolCall]:
        return [
            self._canonical_call(
                state.get("id") or f"call_{uuid.uuid4().hex}",
                state.get("name") or "",
                state.get("arguments") or "",
            )
            for _, state in sorted(raw.items())
        ]

    def _canonical_call(self, call_id: str, name: str, arguments: str) -> CanonicalToolCall:
        if not name:
            raise CodexProtocolError("Provider returned a tool call without a name.")
        tool = self._tools_by_wire.get(name)
        if tool is None:
            raise CodexProtocolError(f"Provider returned undeclared tool call {name!r}.")
        kind = tool.kind
        if kind == "custom":
            try:
                decoded = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise CodexProtocolError(f"Custom tool {name!r} returned invalid wrapper JSON.") from exc
            if not isinstance(decoded, dict) or not isinstance(decoded.get("input"), str):
                raise CodexProtocolError(f"Custom tool {name!r} must return an object containing string field 'input'.")
            arguments = decoded["input"]
        return CanonicalToolCall(
            call_id=call_id,
            name=tool.name,
            arguments=arguments,
            kind=kind,
            namespace=tool.namespace,
        )

    @staticmethod
    def _apply_usage(result: CanonicalResult, usage: dict[str, Any]) -> None:
        result.input_tokens = _non_negative_int(usage.get("prompt_tokens"))
        result.output_tokens = _non_negative_int(usage.get("completion_tokens"))

    def _url(self) -> str:
        base_url = str(self.config.get("baseUrl") or "").rstrip("/")
        if not base_url:
            raise ValueError("Provider baseUrl is required.")
        return base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        api_key = str(self.config.get("apiKey") or "")
        if not api_key:
            raise ValueError("Chat Completions provider apiKey is required.")
        return {"Authorization": f"Bearer {api_key}"}

    def _apply_reasoning(self, payload: dict[str, Any], effort: str) -> None:
        if not effort:
            return
        provider_type = str(self.config.get("type") or "").strip().lower()
        if provider_type == "deepseek":
            if effort not in {"high", "max"}:
                raise CodexProtocolError("DeepSeek Chat conversion supports reasoning_effort 'high' or 'max'.")
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = effort
            return
        if provider_type == "doubao":
            payload["thinking"] = {"type": "enabled"}
            return
        if provider_type == "kimi":
            return
        if provider_type == "zhipu":
            payload["thinking"] = {"type": "enabled"}
        payload["reasoning_effort"] = effort


def _chat_arguments(call: CanonicalToolCall) -> str:
    if call.kind == "custom":
        return json.dumps({"input": call.arguments}, ensure_ascii=False, separators=(",", ":"))
    return call.arguments


def _chat_tool_choice(raw: object) -> object:
    if raw is None or isinstance(raw, str) and raw in {"auto", "none", "required"}:
        return "auto" if raw is None else raw
    if isinstance(raw, dict) and str(raw.get("type") or "") in {"function", "custom"}:
        name = str(raw.get("name") or "").strip()
        if name:
            return {"type": "function", "function": {"name": name}}
    raise CodexProtocolError(f"Unsupported tool_choice for Chat conversion: {raw!r}")


def _text_content(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return "".join(str(part.get("text") or "") for part in raw if isinstance(part, dict))
    raise CodexProtocolError("Provider message content must be a string, array, or null.")


def _chat_reasoning_delta(delta: dict[str, Any]) -> str:
    values = [
        str(delta.get(key) or "")
        for key in ("reasoning_content", "reasoning")
        if isinstance(delta.get(key), str) and delta.get(key)
    ]
    if len(set(values)) > 1:
        raise CodexProtocolError("Chat provider emitted conflicting reasoning delta fields.")
    return values[0] if values else ""


def _json_object(raw: str, owner: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CodexProtocolError(f"{owner} is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise CodexProtocolError(f"{owner} must be an object.")
    return value


def _non_negative_int(raw: Any) -> int:
    return int(raw) if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else 0
