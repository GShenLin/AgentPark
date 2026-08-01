from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class OutputCheckSpec:
    check_id: str
    pattern: str
    required: bool
    weight: int

    @classmethod
    def from_payload(
        cls,
        payload: object,
        *,
        field: str,
        error_type: type[ValueError] = ValueError,
    ) -> "OutputCheckSpec":
        if not isinstance(payload, dict):
            raise error_type(f"{field} must be an object.")
        required_keys = {"id", "pattern"}
        allowed_keys = required_keys | {"required", "weight"}
        missing = sorted(required_keys - set(payload))
        unknown = sorted(set(payload) - allowed_keys)
        if missing:
            raise error_type(f"{field} is missing fields: {', '.join(missing)}.")
        if unknown:
            raise error_type(f"{field} has unknown fields: {', '.join(unknown)}.")
        check_id = _identifier(payload["id"], field=f"{field}.id", error_type=error_type)
        pattern = _non_empty_string(
            payload["pattern"],
            field=f"{field}.pattern",
            error_type=error_type,
        )
        try:
            re.compile(pattern)
        except re.error as exc:
            raise error_type(f"{field}.pattern is invalid: {exc}.") from exc
        required = payload.get("required", True)
        if not isinstance(required, bool):
            raise error_type(f"{field}.required must be a boolean.")
        weight = payload.get("weight", 1)
        if isinstance(weight, bool) or not isinstance(weight, int):
            raise error_type(f"{field}.weight must be an integer.")
        if weight < 1 or weight > 1000:
            raise error_type(f"{field}.weight must be between 1 and 1000.")
        return cls(
            check_id=check_id,
            pattern=pattern,
            required=required,
            weight=weight,
        )


def _non_empty_string(
    value: object,
    *,
    field: str,
    error_type: type[ValueError],
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_type(f"{field} must be a non-empty string.")
    return value.strip()


def _identifier(
    value: object,
    *,
    field: str,
    error_type: type[ValueError],
) -> str:
    text = _non_empty_string(value, field=field, error_type=error_type)
    if any(not (char.isalnum() or char in {"-", "_", "."}) for char in text):
        raise error_type(f"{field} contains invalid characters.")
    return text


__all__ = ["OutputCheckSpec"]
