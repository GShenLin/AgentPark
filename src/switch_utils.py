from __future__ import annotations

from typing import Any


TRUE_SWITCH_VALUES = {"enabled", "enable", "on", "true", "1", "yes", "y"}
FALSE_SWITCH_VALUES = {"disabled", "disable", "off", "false", "0", "no", "n"}


def parse_switch_mode(value: Any, default: str | None = None, *, allow_auto: bool = True) -> str | None:
    if isinstance(value, bool):
        return "enabled" if value else "disabled"
    text = str(value or "").strip().lower()
    if text in TRUE_SWITCH_VALUES:
        return "enabled"
    if text in FALSE_SWITCH_VALUES:
        return "disabled"
    if allow_auto and text == "auto":
        return "auto"
    return default


def parse_bool_switch(value: Any, default: bool | None = None) -> bool | None:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in TRUE_SWITCH_VALUES:
        return True
    if text in FALSE_SWITCH_VALUES:
        return False
    return default


def require_bool_switch(value: Any, field_name: str, *, prefix: str = "") -> bool:
    parsed = parse_bool_switch(value, default=None)
    if parsed is None:
        label = f"{prefix} {field_name}".strip()
        raise ValueError(f"{label} must be a boolean.")
    return parsed
