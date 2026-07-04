from __future__ import annotations

import json
import os
from typing import Any

from src.file_transaction import atomic_write_text


AGENT_CONTEXT_HISTORY_FILENAME = "agent_context_history.json"
AGENT_CONTEXT_HISTORY_SCHEMA_VERSION = 1


def load_agent_context_history(agent: object) -> list[dict[str, Any]]:
    path = agent_context_history_path(agent)
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, dict)]


def save_agent_context_history(agent: object, items: list[dict[str, Any]]) -> None:
    path = agent_context_history_path(agent)
    if not path:
        return
    payload = {
        "schema_version": AGENT_CONTEXT_HISTORY_SCHEMA_VERSION,
        "items": [dict(item) for item in items if isinstance(item, dict)],
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    except OSError:
        return


def agent_context_history_path(agent: object) -> str:
    memory_path = str(getattr(agent, "current_memory_path", "") or "").strip()
    if not memory_path:
        memory = getattr(agent, "memory", None)
        memory_path = str(getattr(memory, "current_memory_path", "") or "").strip()
    if not memory_path:
        return ""
    memory_dir = os.path.dirname(os.path.abspath(memory_path))
    if not memory_dir:
        return ""
    return os.path.join(memory_dir, AGENT_CONTEXT_HISTORY_FILENAME)
