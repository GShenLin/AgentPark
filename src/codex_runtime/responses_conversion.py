from __future__ import annotations

import json
from typing import Any

from .contracts import CanonicalMessage
from .contracts import CanonicalRequest
from .contracts import CanonicalTool
from .contracts import CanonicalToolCall
from .contracts import CodexProtocolError
from .responses_wire import canonical_result_sse
from .responses_wire import canonical_result_to_response
from .responses_wire import message_item
from .responses_wire import reasoning_item
from .responses_wire import stream_completed
from .responses_wire import stream_created
from .responses_wire import stream_failed
from .responses_wire import stream_item_added
from .responses_wire import stream_item_done
from .responses_wire import stream_reasoning_delta
from .responses_wire import stream_reasoning_done
from .responses_wire import stream_reasoning_part_added
from .responses_wire import stream_text_delta
from .responses_wire import tool_call_item


def responses_request_to_canonical(payload: dict[str, Any], *, model: str) -> CanonicalRequest:
    if not isinstance(payload, dict):
        raise CodexProtocolError("Responses request body must be a JSON object.")
    if payload.get("previous_response_id") and not payload.get("input"):
        raise CodexProtocolError(
            "Chat protocol conversion requires complete Responses input; "
            "previous_response_id-only continuation is not supported."
        )

    raw_input = payload.get("input", [])
    embedded_tools = _additional_tools_from_input(raw_input) if isinstance(raw_input, list) else []
    tools = tuple(
        tool
        for item in [*_list(payload.get("tools"), "tools"), *embedded_tools]
        for tool in _convert_tools(item)
    )
    wire_names = [tool.wire_name for tool in tools]
    if len(wire_names) != len(set(wire_names)):
        raise CodexProtocolError("Responses tools collide after namespace flattening.")
    tool_kinds = {(tool.namespace, tool.name): tool.kind for tool in tools}
    messages: list[CanonicalMessage] = []
    instructions = str(payload.get("instructions") or "").strip()
    if instructions:
        messages.append(CanonicalMessage(role="system", content=instructions))

    if isinstance(raw_input, str):
        messages.append(CanonicalMessage(role="user", content=raw_input))
    elif isinstance(raw_input, list):
        _append_input_items(messages, raw_input, tool_kinds)
    else:
        raise CodexProtocolError("Responses input must be a string or array.")

    if not any(message.role != "system" for message in messages):
        raise CodexProtocolError("Responses request contains no conversational input.")

    reasoning = payload.get("reasoning")
    effort = str(reasoning.get("effort") or "").strip() if isinstance(reasoning, dict) else ""
    max_output_tokens = payload.get("max_output_tokens")
    if max_output_tokens is not None and (not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool)):
        raise CodexProtocolError("max_output_tokens must be an integer when provided.")
    return CanonicalRequest(
        model=str(model or payload.get("model") or "").strip(),
        messages=tuple(messages),
        tools=tools,
        stream=bool(payload.get("stream", False)),
        tool_choice=payload.get("tool_choice", "auto"),
        parallel_tool_calls=bool(payload.get("parallel_tool_calls", True)),
        reasoning_effort=effort,
        max_output_tokens=max_output_tokens,
    )


def _append_input_items(
    messages: list[CanonicalMessage],
    items: list[Any],
    tool_kinds: dict[tuple[str, str], str],
) -> None:
    pending_calls: list[CanonicalToolCall] = []

    def flush_calls() -> None:
        if pending_calls:
            messages.append(CanonicalMessage(role="assistant", content="", tool_calls=tuple(pending_calls)))
            pending_calls.clear()

    call_names: dict[str, str] = {}
    for raw in items:
        if not isinstance(raw, dict):
            raise CodexProtocolError("Every Responses input item must be an object.")
        item_type = str(raw.get("type") or "message").strip()
        if item_type == "additional_tools":
            continue
        if item_type in {"function_call", "custom_tool_call", "tool_search_call"}:
            name = "tool_search" if item_type == "tool_search_call" else _required_text(raw, "name", item_type)
            call_id = _required_text(raw, "call_id", item_type)
            namespace = str(raw.get("namespace") or "").strip()
            if item_type == "tool_search_call":
                _require_client_tool_search(raw, item_type)
                kind = "tool_search"
                arguments = _json_arguments(raw.get("arguments"), item_type)
            else:
                kind = (
                    "custom"
                    if item_type == "custom_tool_call"
                    else str(tool_kinds.get((namespace, name)) or "function")
                )
                arguments = raw.get("input") if kind == "custom" else raw.get("arguments")
            if not isinstance(arguments, str):
                raise CodexProtocolError(f"{item_type} arguments must be a string.")
            call = CanonicalToolCall(
                call_id=call_id,
                name=name,
                arguments=arguments,
                kind=kind,  # type: ignore[arg-type]
                namespace=namespace,
            )
            pending_calls.append(call)
            call_names[call_id] = call.wire_name
            continue

        flush_calls()
        if item_type in {"function_call_output", "custom_tool_call_output", "tool_search_output"}:
            call_id = _required_text(raw, "call_id", item_type)
            if item_type == "tool_search_output":
                _require_client_tool_search(raw, item_type)
                tools = _list(raw.get("tools"), "tool_search_output tools")
                content = json.dumps(
                    {
                        "status": str(raw.get("status") or ""),
                        "execution": "client",
                        "tools": tools,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            else:
                content = _tool_output_text(raw.get("output"))
            messages.append(
                CanonicalMessage(
                    role="tool",
                    content=content,
                    tool_call_id=call_id,
                    tool_name=call_names.get(call_id, ""),
                )
            )
            continue
        if item_type == "reasoning":
            # Encrypted/native reasoning cannot be represented by Chat protocols.
            # Omitting it preserves the visible conversation and tool transcript.
            continue
        if item_type != "message":
            raise CodexProtocolError(f"Unsupported Responses input item type for Chat conversion: {item_type}")
        role = str(raw.get("role") or "user").strip().lower()
        if role not in {"system", "developer", "user", "assistant"}:
            raise CodexProtocolError(f"Unsupported Responses message role: {role}")
        canonical_role = "system" if role == "developer" else role
        messages.append(
            CanonicalMessage(
                role=canonical_role,  # type: ignore[arg-type]
                content=_message_content(raw.get("content")),
            )
        )
    flush_calls()


def _additional_tools_from_input(items: list[Any]) -> list[Any]:
    output: list[Any] = []
    for raw in items:
        if not isinstance(raw, dict) or str(raw.get("type") or "message").strip() != "additional_tools":
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role not in {"developer", "system"}:
            raise CodexProtocolError("Responses additional_tools role must be developer or system.")
        output.extend(_list(raw.get("tools"), "additional_tools tools"))
    return output


def _convert_tools(raw: Any) -> tuple[CanonicalTool, ...]:
    if not isinstance(raw, dict):
        raise CodexProtocolError("Every Responses tool must be an object.")
    tool_type = str(raw.get("type") or "").strip()
    if tool_type == "function":
        return (CanonicalTool(
            name=_required_text(raw, "name", "function tool"),
            description=str(raw.get("description") or ""),
            input_schema=_schema(raw.get("parameters"), "function tool parameters"),
        ),)
    if tool_type == "custom":
        name = _required_text(raw, "name", "custom tool")
        return (CanonicalTool(
            name=name,
            description=str(raw.get("description") or ""),
            input_schema={
                "type": "object",
                "properties": {"input": {"type": "string", "description": f"Raw input for {name}."}},
                "required": ["input"],
                "additionalProperties": False,
            },
            kind="custom",
        ),)
    if tool_type == "tool_search":
        _require_client_tool_search(raw, "tool_search tool")
        return (CanonicalTool(
            name="tool_search",
            description=str(raw.get("description") or ""),
            input_schema=_schema(raw.get("parameters"), "tool_search parameters"),
            kind="tool_search",
        ),)
    if tool_type == "namespace":
        namespace = _required_text(raw, "name", "namespace tool")
        children = _list(raw.get("tools"), f"namespace tool {namespace!r} tools")
        if not children:
            raise CodexProtocolError(f"namespace tool {namespace!r} contains no child tools.")
        output: list[CanonicalTool] = []
        for child in children:
            if not isinstance(child, dict) or str(child.get("type") or "") != "function":
                raise CodexProtocolError(f"namespace tool {namespace!r} supports only function children.")
            output.append(
                CanonicalTool(
                    name=_required_text(child, "name", f"namespace tool {namespace!r} child"),
                    description=str(child.get("description") or ""),
                    input_schema=_schema(child.get("parameters"), "namespace child parameters"),
                    namespace=namespace,
                )
            )
        return tuple(output)
    raise CodexProtocolError(f"Unsupported Responses tool type for Chat conversion: {tool_type or '<empty>'}")


def _message_content(raw: Any) -> str | list[dict[str, Any]]:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, list):
        raise CodexProtocolError("Responses message content must be a string or array.")
    content: list[dict[str, Any]] = []
    for part in raw:
        if not isinstance(part, dict):
            raise CodexProtocolError("Responses content parts must be objects.")
        part_type = str(part.get("type") or "").strip()
        if part_type in {"input_text", "output_text", "text"}:
            content.append({"type": "text", "text": str(part.get("text") or "")})
        elif part_type == "input_image":
            image_url = part.get("image_url")
            if not isinstance(image_url, str) or not image_url.strip():
                raise CodexProtocolError("input_image requires a non-empty image_url.")
            content.append({"type": "image_url", "image_url": {"url": image_url}})
        else:
            raise CodexProtocolError(f"Unsupported Responses content part: {part_type or '<empty>'}")
    if all(part.get("type") == "text" for part in content):
        return "".join(str(part.get("text") or "") for part in content)
    return content


def _tool_output_text(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        texts: list[str] = []
        for item in raw:
            if isinstance(item, dict) and str(item.get("type") or "") in {"input_text", "output_text", "text"}:
                texts.append(str(item.get("text") or ""))
            else:
                texts.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(texts)
    return json.dumps(raw, ensure_ascii=False)


def _required_text(raw: dict[str, Any], key: str, owner: str) -> str:
    value = str(raw.get(key) or "").strip()
    if not value:
        raise CodexProtocolError(f"{owner} requires non-empty {key}.")
    return value


def _schema(raw: Any, field_name: str) -> dict[str, Any]:
    if raw is None:
        return {"type": "object", "properties": {}}
    if not isinstance(raw, dict):
        raise CodexProtocolError(f"{field_name} must be an object.")
    return dict(raw)


def _require_client_tool_search(raw: dict[str, Any], owner: str) -> None:
    execution = str(raw.get("execution") or "").strip()
    if execution != "client":
        raise CodexProtocolError(
            f"{owner} requires execution='client' for Chat conversion; got {execution or '<empty>'!r}."
        )


def _json_arguments(raw: Any, owner: str) -> str:
    if not isinstance(raw, dict):
        raise CodexProtocolError(f"{owner} arguments must be an object.")
    return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))


def _list(raw: Any, field_name: str) -> list[Any]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CodexProtocolError(f"{field_name} must be an array.")
    return raw
