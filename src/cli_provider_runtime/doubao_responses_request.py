from __future__ import annotations

"""Represent Codex custom tools and their history using Ark function tools."""

import json
from typing import Any

from .contracts import CodexProtocolError


def prepare_doubao_request(request: dict[str, Any]) -> set[str]:
    tools = request.get("tools", [])
    if not isinstance(tools, list):
        raise CodexProtocolError("Doubao Responses tools must be an array.")
    tools = list(tools)
    inputs = request.get("input")
    if isinstance(inputs, list):
        retained = []
        for item in inputs:
            if isinstance(item, dict) and item.get("type") == "additional_tools":
                if item.get("role") not in {"developer", "system"} or not isinstance(item.get("tools"), list):
                    raise CodexProtocolError("Doubao additional_tools requires an instruction role and tools array.")
                tools.extend(item["tools"])
            else:
                retained.append(item)
        request["input"] = retained
    custom_names: set[str] = set()
    converted = []
    for tool in tools:
        if not isinstance(tool, dict):
            raise CodexProtocolError("Doubao Responses tool must be an object.")
        if tool.get("type") != "custom":
            converted.append(tool)
            continue
        name = tool.get("name")
        if not isinstance(name, str) or not name:
            raise CodexProtocolError("Doubao custom tool requires a name.")
        custom_names.add(name)
        converted.append({
            "type": "function", "name": name,
            "description": str(tool.get("description") or "") +
                "\nPass the raw tool input as the JSON string property 'input'.",
            "parameters": {"type": "object", "properties": {"input": {"type": "string"}},
                           "required": ["input"], "additionalProperties": False},
        })
    if tools or "tools" in request:
        request["tools"] = converted
    choice = request.get("tool_choice")
    if isinstance(choice, dict) and choice.get("type") == "custom":
        request["tool_choice"] = {**choice, "type": "function"}
    if isinstance(request.get("input"), list):
        request["input"] = [_history_item(item) for item in request["input"]]
    return custom_names


def _history_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    kind = item.get("type")
    if kind == "custom_tool_call":
        value = item.get("input")
        if not isinstance(value, str):
            raise CodexProtocolError("Custom tool history input must be a string.")
        return {"type": "function_call", "call_id": _required(item, "call_id"),
                "name": _required(item, "name"),
                "arguments": json.dumps({"input": value}, ensure_ascii=False, separators=(",", ":"))}
    if kind == "custom_tool_call_output":
        return {"type": "function_call_output", "call_id": _required(item, "call_id"),
                "output": _text_output(item.get("output"))}
    return item


def _text_output(output: Any) -> str:
    if isinstance(output, str):
        return output
    if isinstance(output, list) and all(
        isinstance(part, dict) and part.get("type") in {"input_text", "output_text", "text"}
        and isinstance(part.get("text"), str) for part in output
    ):
        return "\n".join(part["text"] for part in output)
    raise CodexProtocolError("Doubao custom tool output requires text; non-text results need an explicit media mapping.")


def _required(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value:
        raise CodexProtocolError(f"Doubao custom tool history requires {key}.")
    return value


def unwrap_custom_arguments(arguments: Any) -> str:
    if not isinstance(arguments, str):
        raise CodexProtocolError("Doubao custom tool wrapper arguments must be a JSON string.")
    try:
        value = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise CodexProtocolError("Doubao custom tool wrapper arguments are not valid JSON.") from exc
    if not isinstance(value, dict) or set(value) != {"input"} or not isinstance(value["input"], str):
        raise CodexProtocolError("Doubao custom tool wrapper must contain exactly one string 'input' field.")
    return value["input"]
