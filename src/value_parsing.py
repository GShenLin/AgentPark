import json
from typing import Any


def parse_bool_value(
    value: object,
    default: bool = False,
    *,
    true_values: tuple[str, ...] = ("true",),
    false_values: tuple[str, ...] = ("false",),
) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text in true_values:
        return True
    if text in false_values:
        return False
    return default


def parse_int_value(
    value: object,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        parsed = default
    if minimum is not None and parsed < minimum:
        parsed = minimum
    if maximum is not None and parsed > maximum:
        parsed = maximum
    return parsed


def parse_float_value(value: object, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def parse_optional_bool_value(
    name: str,
    value: object,
    *,
    true_values: tuple[str, ...] = ("true",),
    false_values: tuple[str, ...] = ("false",),
) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in true_values:
        return True
    if text in false_values:
        return False
    raise ValueError(f"{name} must be a boolean value.")


def parse_optional_int_value(
    name: str,
    value: object,
    *,
    allowed_values: tuple[int, ...] = (),
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer.")
    try:
        parsed = int(float(value))
    except Exception as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if parsed in allowed_values:
        return parsed
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}.")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{name} must be <= {maximum}.")
    return parsed


def parse_optional_float_value(
    name: str,
    value: object,
    *,
    minimum_exclusive: float | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number.")
    try:
        parsed = float(value)
    except Exception as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if minimum_exclusive is not None and parsed <= minimum_exclusive:
        raise ValueError(f"{name} must be greater than {minimum_exclusive:g}.")
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum:g}.")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{name} must be <= {maximum:g}.")
    return parsed


def parse_json_value(value: object, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        return json.loads(text)
    except Exception:
        return fallback
