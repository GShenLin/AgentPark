from __future__ import annotations

from ..workspace_settings import load_workspace_settings


DEFAULT_MAX_ACTIVE_MEMORY_ENTRIES = 20


def read_max_active_memory_entries() -> int:
    try:
        payload = load_workspace_settings()
    except Exception:
        return DEFAULT_MAX_ACTIVE_MEMORY_ENTRIES
    node_memory = payload.get("nodeMemory") if isinstance(payload, dict) else None
    if node_memory is None and isinstance(payload, dict):
        node_memory = payload.get("node_memory")
    if not isinstance(node_memory, dict):
        return DEFAULT_MAX_ACTIVE_MEMORY_ENTRIES

    raw = None
    for key in ("maxEntries", "max_entries", "maxActiveEntries", "max_active_entries"):
        if key in node_memory:
            raw = node_memory.get(key)
            break
    if raw is None or raw == "":
        return DEFAULT_MAX_ACTIVE_MEMORY_ENTRIES
    try:
        value = int(float(raw))
    except Exception:
        return DEFAULT_MAX_ACTIVE_MEMORY_ENTRIES
    return value if value > 0 else DEFAULT_MAX_ACTIVE_MEMORY_ENTRIES
