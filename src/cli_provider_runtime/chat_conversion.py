from __future__ import annotations

import json
from typing import Any

from .contracts import CanonicalMessage
from .contracts import CanonicalRequest
from .contracts import CanonicalTool
from .contracts import CanonicalToolCall
from .contracts import CodexProtocolError


def chat_request_to_canonical(payload: dict[str, Any], *, model: str) -> CanonicalRequest:
    if not isinstance(payload, dict):
        raise CodexProtocolError("Chat Completions request body must be a JSON object.")
    tools = tuple(_tool(item) for item in _array(payload.get("tools"), "tools"))
    declared_tools = {tool.name: tool for tool in tools}
    if len(declared_tools) != len(tools):
        raise CodexProtocolError("Chat Completions tools contain duplicate names.")

    messages: list[CanonicalMessage] = []
    call_names: dict[str, str] = {}
    for raw in _array(payload.get("messages"), "messages"):
        if not isinstance(raw, dict):
            raise CodexProtocolError("Every Chat Completions message must be an object.")
        role = str(raw.get("role") or "").strip()
        if role not in {"system", "developer", "user", "assistant", "tool"}:
            raise CodexProtocolError(f"Unsupported Chat Completions role: {role or '<empty>'}.")
        if role == "tool":
            call_id = _required_text(raw, "tool_call_id", "tool message")
            messages.append(
                CanonicalMessage(
                    role="tool",
                    content=_content(raw.get("content")),
                    tool_call_id=call_id,
                    tool_name=call_names.get(call_id, ""),
                )
            )
            continue
        calls = _tool_calls(raw.get("tool_calls"), call_names)
        messages.append(
            CanonicalMessage(
                role="system" if role == "developer" else role,  # type: ignore[arg-type]
                content=_content(raw.get("content")),
                tool_calls=calls,
            )
        )
    if not any(message.role != "system" for message in messages):
        raise CodexProtocolError("Chat Completions request contains no conversational input.")

    max_tokens = payload.get("max_completion_tokens", payload.get("max_tokens"))
    if max_tokens is not None and (
        not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1
    ):
        raise CodexProtocolError("Chat Completions max tokens must be a positive integer.")
    reasoning_effort = str(payload.get("reasoning_effort") or "").strip()
    return CanonicalRequest(
        model=str(model or payload.get("model") or "").strip(),
        messages=tuple(messages),
        tools=tools,
        stream=bool(payload.get("stream", False)),
        tool_choice=_tool_choice(payload.get("tool_choice")),
        parallel_tool_calls=bool(payload.get("parallel_tool_calls", True)),
        reasoning_effort=reasoning_effort,
        max_output_tokens=max_tokens,
    )


def _tool(raw: Any) -> CanonicalTool:
    if not isinstance(raw, dict) or str(raw.get("type") or "") != "function":
        raise CodexProtocolError("Chat Completions supports only function tools.")
    function = raw.get("function")
    if not isinstance(function, dict):
        raise CodexProtocolError("Chat Completions function tool requires a function object.")
    parameters = function.get("parameters", {"type": "object", "properties": {}})
    if not isinstance(parameters, dict):
        raise CodexProtocolError("Chat Completions function parameters must be an object.")
    return CanonicalTool(
        name=_required_text(function, "name", "function tool"),
        description=str(function.get("description") or ""),
        input_schema=dict(parameters),
    )


def _tool_calls(
    raw: Any,
    call_names: dict[str, str],
) -> tuple[CanonicalToolCall, ...]:
    calls: list[CanonicalToolCall] = []
    for item in _array(raw, "tool_calls"):
        if not isinstance(item, dict) or str(item.get("type") or "function") != "function":
            raise CodexProtocolError("Chat Completions supports only function tool calls.")
        function = item.get("function")
        if not isinstance(function, dict):
            raise CodexProtocolError("Chat Completions tool call requires a function object.")
        call_id = _required_text(item, "id", "tool call")
        name = _required_text(function, "name", "tool call function")
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            raise CodexProtocolError("Chat Completions tool call arguments must be a JSON string.")
        try:
            decoded = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise CodexProtocolError(f"Chat Completions tool call {name!r} arguments are invalid JSON.") from exc
        if not isinstance(decoded, dict):
            raise CodexProtocolError(f"Chat Completions tool call {name!r} arguments must decode to an object.")
        calls.append(CanonicalToolCall(call_id=call_id, name=name, arguments=arguments))
        call_names[call_id] = name
    return tuple(calls)


def _content(raw: Any) -> str | list[dict[str, Any]]:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, list):
        raise CodexProtocolError("Chat Completions message content must be a string, array, or null.")
    parts: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise CodexProtocolError("Chat Completions content parts must be objects.")
        item_type = str(item.get("type") or "")
        if item_type in {"text", "input_text"}:
            parts.append({"type": "text", "text": str(item.get("text") or "")})
        elif item_type in {"image_url", "input_image"}:
            image_url = item.get("image_url")
            if isinstance(image_url, str):
                image_url = {"url": image_url}
            if not isinstance(image_url, dict) or not str(image_url.get("url") or "").strip():
                raise CodexProtocolError("Chat Completions image_url content requires a URL.")
            parts.append({"type": "image_url", "image_url": dict(image_url)})
        else:
            raise CodexProtocolError(f"Unsupported Chat Completions content part: {item_type or '<empty>'}.")
    return parts


def _tool_choice(raw: Any) -> object:
    if raw is None or raw in {"auto", "none", "required"}:
        return "auto" if raw is None else raw
    if not isinstance(raw, dict) or str(raw.get("type") or "") != "function":
        raise CodexProtocolError("Chat Completions tool_choice must be auto, none, required, or a function.")
    function = raw.get("function")
    if not isinstance(function, dict):
        raise CodexProtocolError("Chat Completions function tool_choice requires a function object.")
    return {"type": "function", "name": _required_text(function, "name", "tool_choice function")}


def _required_text(payload: dict[str, Any], key: str, owner: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise CodexProtocolError(f"Chat Completions {owner} requires non-empty {key}.")
    return value


def _array(raw: Any, field_name: str) -> list[Any]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CodexProtocolError(f"Chat Completions {field_name} must be an array.")
    return raw


__all__ = ["chat_request_to_canonical"]
