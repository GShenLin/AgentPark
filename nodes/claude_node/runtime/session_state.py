from __future__ import annotations

# Persists the selected Claude session for a workflow node.
import json
import os
import tempfile


SESSION_STATE_FILENAME = "claude_session.json"
STATE_VERSION = 1


def read_selected_session_id(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Claude session state must be a JSON object.")
    version = payload.get("version")
    if version != STATE_VERSION:
        raise ValueError(f"Unsupported Claude session state version: {version!r}.")
    return str(payload.get("session_id") or "").strip()


def write_selected_session_id(path: str, session_id: str) -> None:
    target = os.path.abspath(path)
    directory = os.path.dirname(target)
    os.makedirs(directory, exist_ok=True)
    payload = {"version": STATE_VERSION, "session_id": str(session_id or "").strip()}
    descriptor, temp_path = tempfile.mkstemp(prefix=".claude-session-", suffix=".json", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, target)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def session_runtime_key(graph_id: str, node_id: str, state_path: str) -> str:
    return "\0".join(
        (
            str(graph_id or "default").strip() or "default",
            str(node_id or "claude").strip() or "claude",
            os.path.normcase(os.path.abspath(state_path)),
        )
    )


__all__ = [
    "SESSION_STATE_FILENAME",
    "read_selected_session_id",
    "session_runtime_key",
    "write_selected_session_id",
]
