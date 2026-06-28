from __future__ import annotations

from typing import Any


class SkillScriptArgumentError(ValueError):
    pass


def validate_script_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise SkillScriptArgumentError("script arguments must be an object")
    if not isinstance(schema, dict):
        raise SkillScriptArgumentError("script args schema must be an object")
    if schema.get("type") != "object":
        raise SkillScriptArgumentError("script args schema type must be object")
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        raise SkillScriptArgumentError("script args schema properties must be an object")
    required = schema.get("required") or []
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise SkillScriptArgumentError("script args schema required must be an array of strings")

    normalized = dict(arguments)
    for key in required:
        if key not in normalized:
            raise SkillScriptArgumentError(f"missing required script argument: {key}")
    if schema.get("additionalProperties") is False:
        unknown = sorted(key for key in normalized if key not in properties)
        if unknown:
            raise SkillScriptArgumentError(f"unknown script argument(s): {', '.join(unknown)}")
    for key, value in normalized.items():
        prop_schema = properties.get(key)
        if isinstance(prop_schema, dict):
            _validate_schema_value(key, value, prop_schema)
    return normalized


def _validate_schema_value(key: str, value: Any, schema: dict[str, Any]) -> None:
    raw_type = schema.get("type")
    if raw_type is None:
        return
    allowed = raw_type if isinstance(raw_type, list) else [raw_type]
    if not all(isinstance(item, str) for item in allowed):
        raise SkillScriptArgumentError(f"script argument schema type for {key} must be a string or array")
    if not any(_matches_json_type(value, item) for item in allowed):
        raise SkillScriptArgumentError(f"script argument {key} must be {' or '.join(allowed)}")


def _matches_json_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    raise SkillScriptArgumentError(f"unsupported script argument schema type: {expected}")
