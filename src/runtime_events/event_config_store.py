from __future__ import annotations

import json
import os
from typing import Any

from src.file_transaction import atomic_write_text, run_with_interprocess_lock
from src.web_backend import runtime_paths


CONFIG_FILENAME = "events.json"


def default_event_config() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "enabled": True,
        "rules": {},
        "context_producers": {
            "builtin.environment_context": {"kind": "builtin", "enabled": True, "priority": "normal"},
            "builtin.tool_failure_context": {"kind": "builtin", "enabled": True, "priority": "high"},
            "builtin.runtime_notice_context": {"kind": "builtin", "enabled": True, "priority": "normal"},
            "builtin.work_persisted_context": {"kind": "builtin", "enabled": True, "priority": "normal"},
            "builtin.work_failed_context": {"kind": "builtin", "enabled": True, "priority": "high"},
        },
        "notice_writers": {
            "builtin.runtime_event_notice": {"kind": "builtin", "enabled": True},
        },
        "receiver_groups": {},
        "context_policy": {
            "default_ttl": "next_turn",
            "max_fragment_chars": 8000,
            "max_artifacts_per_event": 20,
            "dedupe_window_ms": 30000,
        },
    }


def event_config_path() -> str:
    return os.path.join(runtime_paths._get_runtime_root(), "config", CONFIG_FILENAME)


def load_or_create_event_config() -> dict[str, Any]:
    path = event_config_path()

    def load() -> dict[str, Any]:
        if not os.path.exists(path):
            payload = default_event_config()
            _write_unlocked(path, payload)
            return payload
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError(f"{path} must contain a JSON object")
        return payload

    return run_with_interprocess_lock(path + ".lock", load)


def write_event_config(payload: dict[str, Any]) -> None:
    path = event_config_path()
    run_with_interprocess_lock(path + ".lock", lambda: _write_unlocked(path, payload))


def _write_unlocked(path: str, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
