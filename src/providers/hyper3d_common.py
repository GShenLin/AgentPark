from __future__ import annotations

from typing import Any


def parse_hyper3d_int(name: str, value: Any, *, minimum: int | None = None, maximum: int | None = None) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(float(value))
    except Exception as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}.")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{name} must be <= {maximum}.")
    return parsed


def resolve_hyper3d_enum(name: str, value: Any, allowed: set[str]) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(allowed)}.")
    return text


def is_hyper3d_remote_url(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith("http://") or text.startswith("https://")


__all__ = ["is_hyper3d_remote_url", "parse_hyper3d_int", "resolve_hyper3d_enum"]
