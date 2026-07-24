from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any


ZHIPU_RESERVED_REF_PROPERTY = "$ref"
ZHIPU_REF_PROPERTY_ALIAS = "agentpark_ref"


@dataclass(frozen=True)
class ZhipuToolSchemaAdaptation:
    declarations: list[dict[str, Any]]
    aliased_tool_names: frozenset[str]


def adapt_zhipu_tool_declarations(tool_declarations: object) -> ZhipuToolSchemaAdaptation:
    if tool_declarations is None or tool_declarations == ():
        return ZhipuToolSchemaAdaptation(declarations=[], aliased_tool_names=frozenset())
    if not isinstance(tool_declarations, list):
        raise ValueError("Zhipu tool declarations must be a list.")

    declarations: list[dict[str, Any]] = []
    aliased_tool_names: set[str] = set()
    for index, declaration in enumerate(tool_declarations):
        if not isinstance(declaration, dict):
            raise ValueError(f"Zhipu tool declaration at index {index} must be an object.")
        adapted = deepcopy(declaration)
        function = adapted.get("function")
        if not isinstance(function, dict):
            declarations.append(adapted)
            continue
        tool_name = str(function.get("name") or "").strip()
        parameters = function.get("parameters")
        changed = _alias_reserved_ref_properties(parameters, tool_name=tool_name, path="parameters")
        if changed:
            aliased_tool_names.add(tool_name)
            description = function.get("description")
            if isinstance(description, str):
                function["description"] = description.replace(
                    ZHIPU_RESERVED_REF_PROPERTY,
                    ZHIPU_REF_PROPERTY_ALIAS,
                )
            _alias_ref_mentions_in_schema_descriptions(parameters)
        declarations.append(adapted)
    return ZhipuToolSchemaAdaptation(
        declarations=declarations,
        aliased_tool_names=frozenset(aliased_tool_names),
    )


def restore_zhipu_tool_call_arguments(tool_calls: object, *, aliased_tool_names: frozenset[str]) -> object:
    if not isinstance(tool_calls, list) or not aliased_tool_names:
        return tool_calls

    restored_calls = deepcopy(tool_calls)
    for tool_call in restored_calls:
        if not isinstance(tool_call, dict):
            continue
        function = tool_call.get("function")
        if not isinstance(function, dict):
            continue
        tool_name = str(function.get("name") or "").strip()
        if tool_name not in aliased_tool_names:
            continue
        raw_arguments = function.get("arguments")
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                continue
        elif isinstance(raw_arguments, dict):
            arguments = raw_arguments
        else:
            continue
        if not isinstance(arguments, dict):
            continue
        restored = _restore_reserved_ref_arguments(arguments, path=f"{tool_name}.arguments")
        function["arguments"] = json.dumps(restored, ensure_ascii=False, separators=(",", ":"))
    return restored_calls


def _alias_reserved_ref_properties(schema: object, *, tool_name: str, path: str) -> bool:
    if isinstance(schema, list):
        changed = False
        for index, item in enumerate(schema):
            if _alias_reserved_ref_properties(item, tool_name=tool_name, path=f"{path}[{index}]"):
                changed = True
        return changed
    if not isinstance(schema, dict):
        return False

    changed = False
    properties = schema.get("properties")
    if isinstance(properties, dict) and ZHIPU_RESERVED_REF_PROPERTY in properties:
        if ZHIPU_REF_PROPERTY_ALIAS in properties:
            raise ValueError(
                f"Zhipu tool schema alias collision for {tool_name or '<unnamed>'} at {path}.properties: "
                f"both {ZHIPU_RESERVED_REF_PROPERTY!r} and {ZHIPU_REF_PROPERTY_ALIAS!r} are declared."
            )
        schema["properties"] = {
            (ZHIPU_REF_PROPERTY_ALIAS if key == ZHIPU_RESERVED_REF_PROPERTY else key): value
            for key, value in properties.items()
        }
        required = schema.get("required")
        if isinstance(required, list):
            schema["required"] = [
                ZHIPU_REF_PROPERTY_ALIAS if item == ZHIPU_RESERVED_REF_PROPERTY else item
                for item in required
            ]
        changed = True

    for key, value in list(schema.items()):
        if isinstance(value, (dict, list)):
            if _alias_reserved_ref_properties(value, tool_name=tool_name, path=f"{path}.{key}"):
                changed = True
    return changed


def _alias_ref_mentions_in_schema_descriptions(schema: object) -> None:
    if isinstance(schema, list):
        for item in schema:
            _alias_ref_mentions_in_schema_descriptions(item)
        return
    if not isinstance(schema, dict):
        return
    for key, value in schema.items():
        if key == "description" and isinstance(value, str):
            schema[key] = value.replace(ZHIPU_RESERVED_REF_PROPERTY, ZHIPU_REF_PROPERTY_ALIAS)
        elif isinstance(value, (dict, list)):
            _alias_ref_mentions_in_schema_descriptions(value)


def _restore_reserved_ref_arguments(value: object, *, path: str) -> object:
    if isinstance(value, list):
        return [
            _restore_reserved_ref_arguments(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if not isinstance(value, dict):
        return value
    if ZHIPU_REF_PROPERTY_ALIAS in value and ZHIPU_RESERVED_REF_PROPERTY in value:
        raise ValueError(
            f"Zhipu tool arguments contain both {ZHIPU_RESERVED_REF_PROPERTY!r} and "
            f"{ZHIPU_REF_PROPERTY_ALIAS!r} at {path}."
        )
    return {
        (ZHIPU_RESERVED_REF_PROPERTY if key == ZHIPU_REF_PROPERTY_ALIAS else key):
        _restore_reserved_ref_arguments(item, path=f"{path}.{key}")
        for key, item in value.items()
    }


__all__ = [
    "ZHIPU_REF_PROPERTY_ALIAS",
    "ZHIPU_RESERVED_REF_PROPERTY",
    "ZhipuToolSchemaAdaptation",
    "adapt_zhipu_tool_declarations",
    "restore_zhipu_tool_call_arguments",
]
