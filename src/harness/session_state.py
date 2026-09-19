"""Persist node conversation identity independently of runtime configuration."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import uuid

from src.file_transaction import atomic_write_text
from .file_lock import file_lease


def resolve_state_directory(root: Path, *, previous_binding: list[str]) -> Path:
    """Adopt the exact existing binding once, then always use the saved pointer.

    Existing native state stays in place: OpenClaw derives its native session ID
    from this path. Never choose another historical conversation by recency.
    """
    pointer = root / "current-session.json"
    with file_lease(root / ".session-state.lock", exclusive=True):
        if pointer.exists():
            state = json.loads(pointer.read_text(encoding="utf-8"))
            if (not isinstance(state, dict) or type(state.get("schema")) is not int or state["schema"] != 1
                    or not isinstance(state.get("directory"), str)
                    or re.fullmatch(r"[0-9a-f]{24}|[0-9a-f]{32}", state["directory"]) is None):
                raise ValueError(f"Invalid Harness current session: {pointer}")
            directory = root / state["directory"]
            if not directory.is_dir():
                raise ValueError(f"Harness current session directory is missing: {directory}")
            return directory

        previous_id = hashlib.sha256(json.dumps(previous_binding, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]
        directory = root / previous_id
        if any(path.is_dir() and re.fullmatch(r"[0-9a-f]{32}", path.name) for path in root.iterdir()):
            raise ValueError(f"Harness current session pointer is missing; restore {pointer} to resume existing state.")
        if not directory.is_dir():
            if any(path.is_dir() and re.fullmatch(r"[0-9a-f]{24}", path.name) for path in root.iterdir()):
                raise ValueError(
                    "Existing Harness conversations do not match the current configuration. "
                    "Restore the previous Provider, Model, working directory and instruction once "
                    "to adopt that conversation before switching models."
                )
            directory = root / uuid.uuid4().hex
            directory.mkdir()
        atomic_write_text(str(pointer), json.dumps({"schema": 1, "directory": directory.name}) + "\n",
                          encoding="utf-8")
        return directory
