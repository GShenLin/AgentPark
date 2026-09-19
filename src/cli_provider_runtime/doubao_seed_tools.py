from __future__ import annotations

"""Bind Seed calls to this request's declared tools, including Codex exec."""

import json
import re
import uuid
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .contracts import CanonicalTool, CanonicalToolCall, CodexProtocolError
from .doubao_seed_parser import SeedCall
from .responses_conversion import responses_tools_to_canonical
from .responses_wire import tool_call_item


_SHARED_SHELL_PROPERTIES = {
    "workdir": {"type": "string"},
    "login": {"type": "boolean"},
    "justification": {"type": "string"},
    "prefix_rule": {"type": "array", "items": {"type": "string"}},
    "sandbox_permissions": {"enum": ["use_default", "require_escalated"]},
}
_SHELL_SCHEMAS = {
    "exec_command": {
        "type": "object",
        "properties": {
            **_SHARED_SHELL_PROPERTIES,
            "cmd": {"type": "string"},
            "shell": {"type": "string"},
            "tty": {"type": "boolean"},
            "yield_time_ms": {"type": "integer"},
            "max_output_tokens": {"type": "integer"},
        },
        "required": ["cmd"],
        "additionalProperties": False,
    },
    "shell_command": {
        "type": "object",
        "properties": {
            **_SHARED_SHELL_PROPERTIES,
            "command": {"type": "string"},
            "timeout_ms": {"type": "integer"},
        },
        "required": ["command"],
        "additionalProperties": False,
    },
}


class SeedToolRegistry:
    def __init__(self, payload: dict[str, Any]) -> None:
        raw_tools = list(payload.get("tools") or [])
        raw_input = payload.get("input")
        for item in raw_input if isinstance(raw_input, list) else []:
            if isinstance(item, dict) and item.get("type") == "additional_tools":
                if item.get("role") not in {"developer", "system"} or not isinstance(item.get("tools"), list):
                    raise CodexProtocolError("Seed additional_tools requires an instruction role and a tools array.")
                raw_tools.extend(item["tools"])
        # Built-in server tools are not callable through this textual dialect.
        callable_tools = [
            tool for tool in raw_tools
            if isinstance(tool, dict) and tool.get("type") in {"function", "custom", "namespace"}
        ]
        self.tools = responses_tools_to_canonical(callable_tools)
        self.choice = payload.get("tool_choice", "auto")

    def convert(self, call: SeedCall) -> dict[str, Any]:
        if self.choice == "none":
            raise CodexProtocolError("Seed emitted a tool call while tool_choice is 'none'.")
        tool = self._resolve(call.name)
        if tool is not None:
            arguments = _arguments(call, tool.input_schema)
            self._check_choice(tool)
            return tool_call_item(CanonicalToolCall(
                call_id=f"call_seed_{uuid.uuid4().hex}", name=tool.name,
                namespace=tool.namespace, kind=tool.kind,
                arguments=arguments["input"] if tool.kind == "custom" else _json(arguments),
            ))
        return self._shell_via_exec(call)

    def _resolve(self, name: str) -> CanonicalTool | None:
        exact = [tool for tool in self.tools if name in {
            tool.wire_name, f"{tool.namespace}.{tool.name}" if tool.namespace else tool.name,
        }]
        matches = exact or [tool for tool in self.tools if tool.name == name]
        if len(matches) > 1:
            raise CodexProtocolError(f"Seed tool name {name!r} is ambiguous; a namespace is required.")
        return matches[0] if matches else None

    def _check_choice(self, tool: CanonicalTool) -> None:
        if isinstance(self.choice, dict):
            choice_name = self.choice.get("name")
            choice_namespace = self.choice.get("namespace", "")
            if (choice_name, choice_namespace) != (tool.name, tool.namespace):
                raise CodexProtocolError("Seed call does not match the explicitly selected tool.")

    def _shell_via_exec(self, call: SeedCall) -> dict[str, Any]:
        if call.name not in _SHELL_SCHEMAS:
            raise CodexProtocolError(f"Seed returned undeclared tool {call.name!r}.")
        executor = self._resolve("exec")
        if executor is None or executor.kind != "custom":
            raise CodexProtocolError(f"Seed returned undeclared tool {call.name!r} without a Codex exec entry point.")
        self._check_choice(executor)
        # These are the two explicit Codex shell contracts, not arbitrary methods
        # inferred from the model's output. Require the actual nested declaration.
        declared = {
            name for name in _SHELL_SCHEMAS
            if re.search(r"declare const tools:\s*\{\s*" + name + r"\(args:\s*\{", executor.description)
        }
        arguments = _arguments(call, _SHELL_SCHEMAS[call.name])
        target = call.name
        if target not in declared:
            if target != "exec_command" or "shell_command" not in declared:
                raise CodexProtocolError(f"Codex exec does not declare nested tool {target!r}.")
            # The legacy shell contract has no PTY/yield semantics. Only the
            # common, losslessly translatable arguments may cross this boundary.
            target = "shell_command"
            arguments["command"] = arguments.pop("cmd")
            _validate(arguments, _SHELL_SCHEMAS[target], "Seed shell contract conversion")
        source = f"text(await tools.{target}({_json(arguments)}));"
        return tool_call_item(CanonicalToolCall(
            call_id=f"call_seed_{uuid.uuid4().hex}", name=executor.name,
            kind="custom", arguments=source,
        ))


def _arguments(call: SeedCall, schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties", {})
    validator = Draft202012Validator(schema)
    arguments: dict[str, Any] = {}
    for parameter in call.parameters:
        definition = properties.get(parameter.name, {})
        hint = parameter.type_hint
        if hint == "string" or not hint and validator.evolve(schema=definition).is_valid(parameter.text):
            value: Any = parameter.text
        else:
            try:
                value = json.loads(parameter.text, parse_constant=_invalid_constant)
            except (ValueError, json.JSONDecodeError) as exc:
                raise CodexProtocolError(
                    f"Seed parameter {parameter.name!r} requires typed JSON or an explicit string type."
                ) from exc
            if parameter.type_hint:
                _validate(value, {"type": parameter.type_hint}, f"Seed parameter {parameter.name!r}")
        arguments[parameter.name] = value
    _validate(arguments, schema, f"Seed tool {call.name!r} arguments")
    return arguments


def _validate(value: Any, schema: dict[str, Any], owner: str) -> None:
    try:
        Draft202012Validator(schema).validate(value)
    except ValidationError as exc:
        path = ".".join(map(str, exc.absolute_path)) or "<root>"
        # Do not include command bodies or other argument values in errors.
        raise CodexProtocolError(f"{owner} violates {exc.validator} at {path}.") from exc


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant: {value}")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
