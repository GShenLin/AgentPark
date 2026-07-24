from __future__ import annotations

import json
import os

from src.file_transaction import atomic_write_text
from src.file_transaction import run_with_interprocess_lock


THREAD_STATE_VERSION = 2
THREAD_STATE_FILENAME = "codex_session.json"


def read_selected_thread_id(path: str) -> str:
    state_path = _state_path(path)
    return run_with_interprocess_lock(
        f"{state_path}.lock",
        lambda: _read_selected_thread_id_unlocked(state_path),
    )


def write_selected_thread_id(path: str, thread_id: str) -> None:
    state_path = _state_path(path)
    selected_thread_id = str(thread_id or "").strip()
    run_with_interprocess_lock(
        f"{state_path}.lock",
        lambda: _write_selected_thread_id_unlocked(state_path, selected_thread_id),
    )


def session_runtime_key(graph_id: str, node_id: str, state_path: str) -> str:
    return "|".join(
        (
            str(graph_id or "default").strip() or "default",
            str(node_id or "codex").strip() or "codex",
            os.path.normcase(os.path.abspath(state_path)),
        )
    )


def _read_selected_thread_id_unlocked(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to read Codex thread selection {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Codex thread selection must be a JSON object: {path}")
    version = payload.get("version")
    if version not in {1, THREAD_STATE_VERSION}:
        raise RuntimeError(f"Unsupported Codex thread selection version {version!r}: {path}")
    return str(payload.get("thread_id") or "").strip()


def _write_selected_thread_id_unlocked(path: str, thread_id: str) -> None:
    atomic_write_text(
        path,
        json.dumps(
            {
                "version": THREAD_STATE_VERSION,
                "thread_id": thread_id,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _state_path(path: str) -> str:
    resolved = os.path.abspath(str(path or "").strip())
    if not resolved:
        raise ValueError("Codex thread selection path is required.")
    return resolved


__all__ = [
    "THREAD_STATE_FILENAME",
    "THREAD_STATE_VERSION",
    "read_selected_thread_id",
    "session_runtime_key",
    "write_selected_thread_id",
]
