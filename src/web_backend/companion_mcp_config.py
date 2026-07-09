from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..value_parsing import parse_optional_float_value
from ..workspace_settings import load_workspace_settings


DEFAULT_WAIT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_TIMEOUT_SECONDS = 600.0
DEFAULT_SUMMARY_CACHE_TTL_SECONDS = 0.1


@dataclass(frozen=True)
class CompanionMcpConfig:
    default_timeout_seconds: float = DEFAULT_WAIT_TIMEOUT_SECONDS
    max_timeout_seconds: float = DEFAULT_MAX_TIMEOUT_SECONDS
    summary_cache_ttl_seconds: float = DEFAULT_SUMMARY_CACHE_TTL_SECONDS


def read_companion_mcp_config() -> CompanionMcpConfig:
    try:
        settings = load_workspace_settings()
    except Exception:
        settings = {}
    section = _section(settings)
    return CompanionMcpConfig(
        default_timeout_seconds=_positive_float(
            section.get("defaultTimeoutSeconds"),
            default=DEFAULT_WAIT_TIMEOUT_SECONDS,
            field="companionMcp.defaultTimeoutSeconds",
        ),
        max_timeout_seconds=_positive_float(
            section.get("maxTimeoutSeconds"),
            default=DEFAULT_MAX_TIMEOUT_SECONDS,
            field="companionMcp.maxTimeoutSeconds",
        ),
        summary_cache_ttl_seconds=_positive_float(
            section.get("summaryCacheTtlSeconds"),
            default=DEFAULT_SUMMARY_CACHE_TTL_SECONDS,
            field="companionMcp.summaryCacheTtlSeconds",
        ),
    )


def _section(settings: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(settings, dict):
        return {}
    value = settings.get("companionMcp")
    return value if isinstance(value, dict) else {}


def _positive_float(value: object, *, default: float, field: str) -> float:
    if value in (None, ""):
        return float(default)
    try:
        parsed = parse_optional_float_value(field, value, minimum_exclusive=0)
    except ValueError:
        return float(default)
    return float(parsed if parsed is not None else default)


__all__ = [
    "CompanionMcpConfig",
    "DEFAULT_MAX_TIMEOUT_SECONDS",
    "DEFAULT_SUMMARY_CACHE_TTL_SECONDS",
    "DEFAULT_WAIT_TIMEOUT_SECONDS",
    "read_companion_mcp_config",
]
