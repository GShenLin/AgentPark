from __future__ import annotations

import copy
import json
import threading
import time
from dataclasses import dataclass
from typing import Callable, TypeVar


T = TypeVar("T")
DEFAULT_MCP_TOOL_LIST_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class _ToolListEntry:
    expires_at: float
    tools: object


_CACHE: dict[str, _ToolListEntry] = {}
_LOCK = threading.Lock()


def cached_mcp_tool_list(key_payload: object, builder: Callable[[], T], *, ttl_seconds: float) -> T:
    ttl = max(0.0, float(ttl_seconds))
    if ttl <= 0:
        return builder()
    key = _stable_key(key_payload)
    now = time.monotonic()
    with _LOCK:
        entry = _CACHE.get(key)
        if entry and entry.expires_at > now:
            return copy.deepcopy(entry.tools)

    tools = builder()
    with _LOCK:
        _CACHE[key] = _ToolListEntry(expires_at=now + ttl, tools=copy.deepcopy(tools))
    return tools


def invalidate_mcp_tool_list_cache(server_name: str | None = None) -> None:
    prefix = f"{server_name}:" if server_name else ""
    with _LOCK:
        for key in list(_CACHE):
            if not prefix or key.startswith(prefix):
                _CACHE.pop(key, None)


def _stable_key(payload: object) -> str:
    if isinstance(payload, dict) and "name" in payload:
        name = str(payload.get("name") or "")
    else:
        name = ""
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{name}:{stable}"
