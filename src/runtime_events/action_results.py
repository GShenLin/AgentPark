from __future__ import annotations

from typing import Any


def truncate_text(value: object, limit: int) -> str:
    text = str(value or "")
    try:
        safe_limit = max(0, int(limit))
    except Exception:
        safe_limit = 0
    if safe_limit and len(text) > safe_limit:
        return text[: max(0, safe_limit - 3)].rstrip() + "..."
    return text


def context_fragment(content: str, *, ttl: str, priority: str) -> dict[str, Any]:
    return {
        "type": "context_fragment",
        "priority": priority,
        "ttl": ttl,
        "audience": "model",
        "content": content,
    }


def notice(message: str, *, level: str = "info") -> dict[str, Any]:
    return {
        "type": "notice",
        "level": level,
        "message": message,
    }
