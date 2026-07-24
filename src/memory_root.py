from __future__ import annotations

import os

from .workspace_settings import resolve_memories_root


_active_memories_root = ""


def get_memories_root() -> str:
    if _active_memories_root:
        return _active_memories_root
    return configure_memories_root(resolve_memories_root())


def configure_memories_root(path: object) -> str:
    requested_path = resolve_memories_root({"memoriesPath": path})
    fallback_path = resolve_memories_root({})
    try:
        os.makedirs(requested_path, exist_ok=True)
        if not os.path.isdir(requested_path):
            raise NotADirectoryError(requested_path)
        active_path = requested_path
    except OSError:
        os.makedirs(fallback_path, exist_ok=True)
        active_path = fallback_path
    global _active_memories_root
    _active_memories_root = os.path.abspath(active_path)
    return _active_memories_root
