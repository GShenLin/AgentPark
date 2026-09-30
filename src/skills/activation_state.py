"""Conversation-owned skill state. Missing state means no skill was activated."""
from __future__ import annotations

import json
from pathlib import Path

from src.file_transaction import atomic_write_text


SKILL_STATE_FILENAME = "agent_skill_state.json"


def load_active_skills(node_directory: str) -> set[str]:
    if not node_directory:
        return set()
    path = Path(node_directory) / SKILL_STATE_FILENAME
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Invalid skill activation state schema")
    names = payload.get("active_skills")
    if not isinstance(names, list) or any(not isinstance(n, str) or not n.strip() for n in names):
        raise ValueError("Skill activation state requires an array of skill names")
    return set(names)


def save_active_skills(node_directory: str, names: set[str]) -> None:
    if not node_directory:
        return
    path = Path(node_directory) / SKILL_STATE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(str(path), json.dumps({
        "schema_version": 1, "active_skills": sorted(names),
    }, ensure_ascii=False) + "\n")


def clear_active_skills(node_directory: str) -> None:
    path = Path(node_directory) / SKILL_STATE_FILENAME
    if path.exists():
        path.unlink()
