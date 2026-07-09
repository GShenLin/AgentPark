from __future__ import annotations

from ..workspace_settings import load_workspace_settings


DEFAULT_MAX_ACTIVE_MEMORY_ENTRIES = 20


def read_max_active_memory_entries() -> int:
    try:
        payload = load_workspace_settings()
    except Exception:
        return DEFAULT_MAX_ACTIVE_MEMORY_ENTRIES
    node_memory = payload.get("nodeMemory") if isinstance(payload, dict) else None
    if not isinstance(node_memory, dict):
        return DEFAULT_MAX_ACTIVE_MEMORY_ENTRIES

    raw = node_memory.get("maxActiveEntries")
    if raw is None or raw == "":
        return DEFAULT_MAX_ACTIVE_MEMORY_ENTRIES
    try:
        value = int(float(raw))
    except Exception:
        return DEFAULT_MAX_ACTIVE_MEMORY_ENTRIES
    return value if value > 0 else DEFAULT_MAX_ACTIVE_MEMORY_ENTRIES
