from __future__ import annotations

import json
from typing import Any

from src.cli_provider_runtime.contracts import CanonicalMessage
from src.cli_provider_runtime.contracts import CanonicalRequest
from src.cli_provider_runtime.contracts import CanonicalTool
from src.cli_provider_runtime.contracts import CanonicalToolCall
from src.cli_provider_runtime.contracts import CodexProtocolError


def messages_request_to_canonical(payload: dict[str, Any], *, model: str) -> CanonicalRequest:
    if not isinstance(payload, dict):
        raise CodexProtocolError("Claude Messages request body must be a JSON object.")
    tools = tuple(_tool(item) for item in _array(payload.get("tools"), "tools"))
    tool_names = [tool.wire_name for tool in tools]
    if len(tool_names) != len(set(tool_names)):
        raise CodexProtocolError("Claude Messages tools contain duplicate names.")

    messages: list[CanonicalMessage] = []
    system_text = _system_text(payload.get("system"))
    if system_text:
        messages.append(CanonicalMessage(role="system", content=system_text))
    call_names: dict[str, str] = {}
    for raw in _array(payload.get("messages"), "messages"):
        if not isinstance(raw, dict):
            raise CodexProtocolError("Every Claude Messages message must be an object.")
        role = str(raw.get("role") or "").strip()
        if role not in {"system", "user", "assistant"}:
            raise CodexProtocolError(f"Unsupported Claude Messages role: {role or '<empty>'}.")
        if role == "system":
            system_message = _system_text(raw.get("content"))
            if system_message:
                messages.append(CanonicalMessage(role="system", content=system_message))
            continue
        _append_message(messages, role, raw.get("content"), call_names)
    if not any(message.role != "system" for message in messages):
        raise CodexProtocolError("Claude Messages request contains no conversational input.")

    max_tokens = payload.get("max_tokens")
    if max_tokens is not None and (
        not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1
    ):
        raise CodexProtocolError("Claude Messages max_tokens must be a positive integer.")
    return CanonicalRequest(
        model=str(model or payload.get("model") or "").strip(),
        messages=tuple(messages),
        tools=tools,
        stream=bool(payload.get("stream", False)),
        tool_choice=_tool_choice(payload.get("tool_choice")),
        parallel_tool_calls=_parallel_tool_calls(payload.get("tool_choice")),
        reasoning_effort=_reasoning_effort(payload),
        max_output_tokens=max_tokens,
    )


def _append_message(
    output: list[CanonicalMessage],
    role: str,
    raw_content: Any,
    call_names: dict[str, str],
) -> None:
    blocks = [{"type": "text", "text": raw_content}] if isinstance(raw_content, str) else _array(raw_content, "content")
    content_parts: list[dict[str, Any]] = []
    tool_calls: list[CanonicalToolCall] = []

    def flush_text_and_calls() -> None:
        if not content_parts and not tool_calls:
            return
        content: str | list[dict[str, Any]]
        if all(str(part.get("type") or "") == "text" for part in content_parts):
            content = "".join(str(part.get("text") or "") for part in content_parts)
        else:
            content = list(content_parts)
        output.append(
            CanonicalMessage(
                role="assistant" if role == "assistant" else "user",
                content=content,
                tool_calls=tuple(tool_calls),
            )
        )
        content_parts.clear()
        tool_calls.clear()

    for block in blocks:
        if not isinstance(block, dict):
            raise CodexProtocolError("Claude Messages content blocks must be objects.")
        block_type = str(block.get("type") or "").strip()
        if block_type == "text":
            content_parts.append({"type": "text", "text": str(block.get("text") or "")})
            continue
        if block_type in {"thinking", "redacted_thinking"}:
            continue
        if role == "assistant" and block_type == "tool_use":
            call_id = _required_text(block, "id", "tool_use")
            name = _required_text(block, "name", "tool_use")
            arguments = block.get("input")
            if not isinstance(arguments, dict):
                raise CodexProtocolError("Claude tool_use input must be an object.")
            tool_calls.append(
                CanonicalToolCall(
                    call_id=call_id,
                    name=name,
                    arguments=json.dumps(arguments, ensure_ascii=False, separators=(",", ":")),
                )
            )
            call_names[call_id] = name
            continue
        if role == "user" and block_type == "tool_result":
            flush_text_and_calls()
            call_id = _required_text(block, "tool_use_id", "tool_result")
            output.append(
                CanonicalMessage(
                    role="tool",
                    content=_tool_result_text(block.get("content")),
                    tool_call_id=call_id,
                    tool_name=call_names.get(call_id, ""),
                )
            )
            continue
        if block_type == "image":
            content_parts.append(_image_part(block))
            continue
        raise CodexProtocolError(
            f"Unsupported Claude Messages {role} content block: {block_type or '<empty>'}."
        )
    flush_text_and_calls()


def _tool(raw: Any) -> CanonicalTool:
    if not isinstance(raw, dict):
        raise CodexProtocolError("Every Claude Messages tool must be an object.")
    schema = raw.get("input_schema")
    if not isinstance(schema, dict):
        raise CodexProtocolError("Claude Messages tool input_schema must be an object.")
    return CanonicalTool(
        name=_required_text(raw, "name", "tool"),
        description=str(raw.get("description") or ""),
        input_schema=dict(schema),
    )


def _system_text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    texts: list[str] = []
    for block in _array(raw, "system"):
        if not isinstance(block, dict) or str(block.get("type") or "") != "text":
            raise CodexProtocolError("Claude Messages system supports only text blocks.")
        texts.append(str(block.get("text") or ""))
    return "\n\n".join(texts)


def _tool_choice(raw: Any) -> object:
    if raw is None:
        return "auto"
    if not isinstance(raw, dict):
        raise CodexProtocolError("Claude Messages tool_choice must be an object.")
    choice_type = str(raw.get("type") or "").strip()
    if choice_type == "auto":
        return "auto"
    if choice_type == "none":
        return "none"
    if choice_type == "any":
        return "required"
    if choice_type == "tool":
        return {"type": "function", "name": _required_text(raw, "name", "tool_choice")}
    raise CodexProtocolError(f"Unsupported Claude Messages tool_choice: {choice_type or '<empty>'}.")


def _parallel_tool_calls(raw: Any) -> bool:
    return not bool(raw.get("disable_parallel_tool_use")) if isinstance(raw, dict) else True


def _reasoning_effort(payload: dict[str, Any]) -> str:
    output_config = payload.get("output_config")
    effort = str(output_config.get("effort") or "").strip() if isinstance(output_config, dict) else ""
    return effort if effort in {"low", "medium", "high", "xhigh", "max"} else ""


def _image_part(block: dict[str, Any]) -> dict[str, Any]:
    source = block.get("source")
    if not isinstance(source, dict):
        raise CodexProtocolError("Claude image block requires a source object.")
    source_type = str(source.get("type") or "")
    if source_type == "url":
        url = _required_text(source, "url", "image source")
    elif source_type == "base64":
        media_type = _required_text(source, "media_type", "image source")
        data = _required_text(source, "data", "image source")
        url = f"data:{media_type};base64,{data}"
    else:
        raise CodexProtocolError(f"Unsupported Claude image source: {source_type or '<empty>'}.")
    return {"type": "image_url", "image_url": {"url": url}}


def _tool_result_text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    values: list[str] = []
    for item in _array(raw, "tool_result content"):
        if isinstance(item, dict) and str(item.get("type") or "") == "text":
            values.append(str(item.get("text") or ""))
        else:
            values.append(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(values)


def _required_text(payload: dict[str, Any], key: str, owner: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise CodexProtocolError(f"Claude Messages {owner} requires non-empty {key}.")
    return value


def _array(raw: Any, field_name: str) -> list[Any]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CodexProtocolError(f"Claude Messages {field_name} must be an array.")
    return raw


__all__ = ["messages_request_to_canonical"]
