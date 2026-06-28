from __future__ import annotations

from typing import Any, Callable

from src.value_parsing import parse_optional_float_value


class ToolTimeoutConfigError(ValueError):
    pass


def resolve_tool_timeout_seconds(
    *,
    config: dict[str, Any] | None,
    name: str | None = None,
    func: Callable | None = None,
    default_timeout: float = 5,
) -> float | None:
    payload = config if isinstance(config, dict) else {}

    if isinstance(name, str) and name.strip():
        key_name = name.strip()
        sec_by_name = payload.get("toolExecutionTimeoutSecByName")
        if isinstance(sec_by_name, dict) and key_name in sec_by_name:
            return _to_timeout_seconds(
                sec_by_name.get(key_name),
                field_name=f"toolExecutionTimeoutSecByName.{key_name}",
            )

        ms_by_name = payload.get("toolExecutionTimeoutMsByName")
        if isinstance(ms_by_name, dict) and key_name in ms_by_name:
            return _milliseconds_to_seconds(
                ms_by_name.get(key_name),
                field_name=f"toolExecutionTimeoutMsByName.{key_name}",
            )

    sec_value = payload.get("toolExecutionTimeoutSec")
    if sec_value is not None:
        return _to_timeout_seconds(sec_value, field_name="toolExecutionTimeoutSec")

    ms_value = payload.get("toolExecutionTimeoutMs")
    if ms_value is not None:
        return _milliseconds_to_seconds(ms_value, field_name="toolExecutionTimeoutMs")

    if callable(func):
        if hasattr(func, "tool_timeout_seconds"):
            return _to_timeout_seconds(
                getattr(func, "tool_timeout_seconds"),
                field_name=f"{getattr(func, '__name__', 'tool')}.tool_timeout_seconds",
            )
        if hasattr(func, "_tool_timeout_seconds"):
            return _to_timeout_seconds(
                getattr(func, "_tool_timeout_seconds"),
                field_name=f"{getattr(func, '__name__', 'tool')}._tool_timeout_seconds",
            )

    return default_timeout


def _milliseconds_to_seconds(value: Any, *, field_name: str) -> float | None:
    try:
        parsed_ms = parse_optional_float_value(field_name, value)
    except ValueError as exc:
        raise ToolTimeoutConfigError(str(exc)) from exc
    if parsed_ms is None:
        raise ToolTimeoutConfigError(f"{field_name} must be a number.")
    return _to_timeout_seconds(parsed_ms / 1000.0, field_name=field_name)


def _to_timeout_seconds(value: Any, *, field_name: str) -> float | None:
    try:
        parsed = parse_optional_float_value(field_name, value)
    except ValueError as exc:
        raise ToolTimeoutConfigError(str(exc)) from exc
    if parsed is None:
        raise ToolTimeoutConfigError(f"{field_name} must be a number.")
    if parsed <= 0:
        return None
    return parsed
