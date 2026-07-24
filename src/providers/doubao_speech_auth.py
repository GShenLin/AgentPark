"""Authentication boundary for Doubao speech data-plane APIs."""
from __future__ import annotations

from collections.abc import Mapping


def resolve_doubao_x_api_key(config: Mapping[str, object] | None) -> str:
    values = config if isinstance(config, Mapping) else {}
    return str(values.get("xApiKey") or "").strip()


def require_doubao_x_api_key(
    config: Mapping[str, object] | None,
    operation: str,
) -> str:
    api_key = resolve_doubao_x_api_key(config)
    if not api_key:
        raise ValueError(f"{operation} requires provider xApiKey.")
    return api_key


__all__ = ["require_doubao_x_api_key", "resolve_doubao_x_api_key"]
