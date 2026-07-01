from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

from src.file_transaction import atomic_write_text
from src.workspace_settings import get_workspace_root


PROFILE_SCHEMA_VERSION = 1


class ProfileStorageError(RuntimeError):
    pass


class ProfileValidationError(ValueError):
    pass


def profile_config_path(filename: str) -> str:
    return os.path.join(get_workspace_root(), "config", filename)


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


def read_profile_document(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {"version": PROFILE_SCHEMA_VERSION, "profiles": []}
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
    profiles = payload.get("profiles")
    if profiles is None:
        profiles = []
    if not isinstance(profiles, list):
        raise ProfileStorageError(f"profile file field profiles must be a list: {path}")
    return {"version": PROFILE_SCHEMA_VERSION, "profiles": [p for p in profiles if isinstance(p, dict)]}


def write_profile_document(path: str, payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ProfileStorageError("profile payload must be an object")
    profiles = payload.get("profiles")
    if not isinstance(profiles, list):
        raise ProfileStorageError("profile payload profiles must be a list")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = json.dumps({"version": PROFILE_SCHEMA_VERSION, "profiles": profiles}, ensure_ascii=False, indent=2) + "\n"
    try:
        atomic_write_text(path, text)
    except Exception as exc:
        raise ProfileStorageError(f"failed to write profile file {path}: {type(exc).__name__}: {exc}") from exc


def upsert_profile(path: str, profile: dict[str, Any]) -> dict[str, Any]:
    profile_id = validate_profile_id(profile.get("id"))
    document = read_profile_document(path)
    profiles = list(document.get("profiles") or [])
    now = now_profile_timestamp()
    next_profile = dict(profile)
    next_profile["id"] = profile_id
    next_profile["updated_at"] = now

    replaced = False
    for index, existing in enumerate(profiles):
        if not isinstance(existing, dict):
            continue
        if str(existing.get("id") or "") != profile_id:
            continue
        next_profile["created_at"] = str(existing.get("created_at") or now)
        profiles[index] = next_profile
        replaced = True
        break

    if not replaced:
        next_profile["created_at"] = now
        profiles.append(next_profile)

    profiles.sort(key=lambda item: str(item.get("name") or item.get("id") or "").lower())
    write_profile_document(path, {"version": PROFILE_SCHEMA_VERSION, "profiles": profiles})
    return next_profile


def get_profile(path: str, profile_id: str) -> dict[str, Any] | None:
    safe_profile_id = validate_profile_id(profile_id)
    document = read_profile_document(path)
    for profile in document.get("profiles") or []:
        if isinstance(profile, dict) and str(profile.get("id") or "") == safe_profile_id:
            return dict(profile)
    return None

