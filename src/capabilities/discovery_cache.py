from __future__ import annotations

import copy
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, TypeVar


T = TypeVar("T")
DEFAULT_DISCOVERY_CACHE_TTL_SECONDS = 2.0


@dataclass(frozen=True)
class _CacheEntry:
    marker: tuple[int, int]
    expires_at: float
    value: object


_CACHE: dict[tuple[str, str], _CacheEntry] = {}
_LOCK = threading.Lock()


def cached_discovery_value(
    namespace: str,
    root: str,
    builder: Callable[[], T],
    *,
    ttl_seconds: float = DEFAULT_DISCOVERY_CACHE_TTL_SECONDS,
) -> T:
    resolved_root = os.path.realpath(os.path.abspath(root))
    key = (str(namespace or "").strip(), os.path.normcase(resolved_root))
    marker = _root_marker(resolved_root)
    now = time.monotonic()
    with _LOCK:
        entry = _CACHE.get(key)
        if entry and entry.marker == marker and entry.expires_at > now:
            return copy.deepcopy(entry.value)

    value = builder()
    with _LOCK:
        _CACHE[key] = _CacheEntry(
            marker=marker,
            expires_at=now + max(0.0, float(ttl_seconds)),
            value=copy.deepcopy(value),
        )
    return value


def invalidate_discovery_cache(namespace: str | None = None, root: str | None = None) -> None:
    normalized_namespace = str(namespace or "").strip()
    normalized_root = os.path.normcase(os.path.realpath(os.path.abspath(root))) if root else ""
    with _LOCK:
        for key in list(_CACHE):
            key_namespace, key_root = key
            if normalized_namespace and key_namespace != normalized_namespace:
                continue
            if normalized_root and key_root != normalized_root:
                continue
            _CACHE.pop(key, None)


def _root_marker(root: str) -> tuple[int, int]:
    try:
        stat = os.stat(root)
    except OSError:
        return (0, 0)
    return (int(getattr(stat, "st_mtime_ns", 0)), int(getattr(stat, "st_size", 0)))
