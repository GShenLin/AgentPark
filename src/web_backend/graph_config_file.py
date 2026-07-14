from __future__ import annotations

import json
import os

from src.file_transaction import atomic_write_text

from .graph_runtime_registry import GraphConfigReadError


def graph_config_version(config_path: str) -> int:
    try:
        return int(os.stat(config_path).st_mtime_ns)
    except OSError:
        return 0


def write_graph_config(config_path: str, payload: dict) -> None:
    if not isinstance(payload, dict):
        raise ValueError("graph config payload must be an object")
    atomic_write_text(config_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def read_graph_config(config_path: str) -> dict:
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise GraphConfigReadError(
            f"graph config contains invalid JSON: {config_path}: line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise GraphConfigReadError(
            f"failed to read graph config {config_path}: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise GraphConfigReadError(f"graph config must be a JSON object: {config_path}")
    if "private" in payload and not isinstance(payload.get("private"), bool):
        raise GraphConfigReadError(f"graph config field 'private' must be a boolean: {config_path}")
    return payload


__all__ = ["graph_config_version", "read_graph_config", "write_graph_config"]
