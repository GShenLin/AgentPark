import os
import re


_LOCALHOST_ORIGIN_PATTERN = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$", re.IGNORECASE)


def configured_cors_allow_origins() -> list[str]:
    raw_value = str(os.environ.get("AGENTPARK_CORS_ALLOW_ORIGINS") or "").strip()
    if not raw_value:
        return []
    origins = [origin.strip() for origin in raw_value.split(",") if origin.strip()]
    return origins or []


def cors_allow_origin_regex() -> str:
    return _LOCALHOST_ORIGIN_PATTERN.pattern


def cors_allows_all_origins() -> bool:
    return "*" in configured_cors_allow_origins()


def private_network_access_enabled() -> bool:
    raw_value = str(os.environ.get("AGENTPARK_ALLOW_PRIVATE_NETWORK_ACCESS") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def is_allowed_private_network_origin(origin: str) -> bool:
    if cors_allows_all_origins():
        return True
    if origin in configured_cors_allow_origins():
        return True
    return bool(_LOCALHOST_ORIGIN_PATTERN.match(str(origin or "").strip()))


__all__ = [
    "configured_cors_allow_origins",
    "cors_allow_origin_regex",
    "is_allowed_private_network_origin",
    "private_network_access_enabled",
]
