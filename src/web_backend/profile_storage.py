from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

from src.file_transaction import atomic_write_text
from src.workspace_settings import get_workspace_root


PROFILE_SCHEMA_VERSION = 1
AGENT_PROFILE_DIR = "agent"
GRAPH_PROFILE_DIR = "graph"


class ProfileStorageError(RuntimeError):
    pass


class ProfileValidationError(ValueError):
    pass


def profile_category_dir(dirname: str) -> str:
    text = str(dirname or "").strip()
    if text not in {AGENT_PROFILE_DIR, GRAPH_PROFILE_DIR}:
        raise ProfileValidationError("profile directory must be agent or graph")
    return os.path.join(get_workspace_root(), text)


def now_profile_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def validate_profile_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ProfileValidationError("profile_id is required")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", text):
        raise ProfileValidationError("profile_id must contain only letters, numbers, underscores, or hyphens")
    return text


def validate_explicit_graph_id(graph_runtime: object, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ProfileValidationError("graph_id is required")
    safe = graph_runtime._sanitize_graph_id(text)
    if safe != text:
        raise ProfileValidationError("graph_id must contain only letters, numbers, underscores, or hyphens")
    return safe


def sanitize_existing_graph_id(graph_runtime: object, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ProfileValidationError("graph_id is required")
    safe = graph_runtime._sanitize_graph_id(text)
    if not safe:
        raise ProfileValidationError("invalid graph_id")
    return safe


def sanitize_existing_node_id(graph_runtime: object, value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ProfileValidationError("node_id is required")
    safe = graph_runtime._sanitize_node_id(text)
    if not safe:
        raise ProfileValidationError("invalid node_id")
    return safe


def profile_file_path(directory: str, profile_id: str) -> str:
    safe_profile_id = validate_profile_id(profile_id)
    return os.path.join(directory, f"{safe_profile_id}.json")


def read_profile_file(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        raise ProfileStorageError(f"profile file does not exist: {path}")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ProfileStorageError(
            f"profile file contains invalid JSON: {path}: line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise ProfileStorageError(f"failed to read profile file {path}: {type(exc).__name__}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProfileStorageError(f"profile file must be a JSON object: {path}")
    profile_id = validate_profile_id(payload.get("id"))
    expected_id = os.path.splitext(os.path.basename(path))[0]
    if profile_id != expected_id:
        raise ProfileStorageError(f"profile file id must match filename: {path}")
    return dict(payload)


def read_profile_document(directory: str) -> dict[str, Any]:
    if not os.path.isdir(directory):
        return {"version": PROFILE_SCHEMA_VERSION, "profiles": []}
    profiles: list[dict[str, Any]] = []
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if not os.path.isfile(path) or not name.lower().endswith(".json"):
            continue
        profiles.append(read_profile_file(path))
    profiles.sort(key=lambda item: str(item.get("name") or item.get("id") or "").lower())
    return {"version": PROFILE_SCHEMA_VERSION, "profiles": profiles}


def write_profile_file(path: str, profile: dict[str, Any]) -> None:
    if not isinstance(profile, dict):
        raise ProfileStorageError("profile payload must be an object")
    profile_id = validate_profile_id(profile.get("id"))
    expected_id = os.path.splitext(os.path.basename(path))[0]
    if profile_id != expected_id:
        raise ProfileStorageError("profile payload id must match profile filename")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps(profile, ensure_ascii=False, indent=2) + "\n"
    try:
        atomic_write_text(path, text)
    except Exception as exc:
        raise ProfileStorageError(f"failed to write profile file {path}: {type(exc).__name__}: {exc}") from exc


def upsert_profile(directory: str, profile: dict[str, Any]) -> dict[str, Any]:
    profile_id = validate_profile_id(profile.get("id"))
    now = now_profile_timestamp()
    next_profile = dict(profile)
    next_profile["id"] = profile_id
    next_profile["updated_at"] = now
    path = profile_file_path(directory, profile_id)

    if os.path.exists(path):
        existing = read_profile_file(path)
        next_profile["created_at"] = str(existing.get("created_at") or now)
    else:
        next_profile["created_at"] = now

    write_profile_file(path, next_profile)
    return next_profile


def get_profile(directory: str, profile_id: str) -> dict[str, Any] | None:
    safe_profile_id = validate_profile_id(profile_id)
    path = profile_file_path(directory, safe_profile_id)
    if not os.path.exists(path):
        return None
    return read_profile_file(path)


def delete_profile(directory: str, profile_id: str) -> bool:
    safe_profile_id = validate_profile_id(profile_id)
    path = profile_file_path(directory, safe_profile_id)
    if not os.path.exists(path):
        return False
    try:
        os.remove(path)
    except OSError as exc:
        raise ProfileStorageError(f"failed to delete profile file {path}: {type(exc).__name__}: {exc}") from exc
    return True
