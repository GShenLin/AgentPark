from __future__ import annotations

from typing import Any


SWITCH_VALUES = {"enabled", "disabled"}


def parse_switch_mode(value: Any, default: str | None = None, *, allow_auto: bool = True) -> str | None:
    if not isinstance(value, str):
        return default
    text = value.strip()
    if text in SWITCH_VALUES:
        return text
    if allow_auto and text == "auto":
        return "auto"
    return default


def parse_bool_switch(value: Any, default: bool | None = None) -> bool | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return default


def require_bool_switch(value: Any, field_name: str, *, prefix: str = "") -> bool:
    parsed = parse_bool_switch(value, default=None)
    if parsed is None:
        label = f"{prefix} {field_name}".strip()
        raise ValueError(f"{label} must be a boolean.")
    return parsed
