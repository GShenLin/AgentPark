from __future__ import annotations

import json
import os
import uuid
from typing import Any

from src.companion_notice_settings import companion_node_review_enabled
from src.companion_paths import companion_node_config_path
from src.file_transaction import append_text
from src.file_transaction import atomic_write_text
from src.file_transaction import run_with_interprocess_lock
from src.message_protocol import now_text
from src.companion_notice_format import format_node_review as _format_node_review_notice
from src.companion_notice_format import format_tool_failure as _format_tool_failure_memory_notice


COMPANION_INBOX_FILENAME = "inbox.jsonl"
NOTICE_TYPES = {"node_review_notice", "tool_failure_memory_notice"}


def companion_config_path() -> str:
    from src.web_backend import runtime_paths

    return companion_node_config_path(runtime_paths._get_graphs_dir())


def companion_inbox_path(config_path: str = "") -> str:
    path = str(config_path or "").strip() or companion_config_path()
    if not path:
        return ""
    return os.path.join(os.path.dirname(path), COMPANION_INBOX_FILENAME)


def deliver_companion_notice(
    notice: dict[str, Any],
    *,
    config_path: str = "",
    delivery_enabled: bool | None = None,
) -> bool:
    path = str(config_path or "").strip() or companion_config_path()
    if not path or not os.path.isfile(path):
        return False
    record = normalize_companion_notice(notice)
    enabled = companion_node_review_enabled() if delivery_enabled is None else bool(delivery_enabled)
    if not enabled:
        return False
    inbox_path = companion_inbox_path(path)

    def write() -> None:
        append_text(inbox_path, json.dumps(record, ensure_ascii=False) + "\n")

    run_with_interprocess_lock(inbox_path + ".lock", write)
    return True


def drain_companion_notices(*, config_path: str = "") -> list[dict[str, Any]]:
    path = companion_inbox_path(config_path)
    if not path or not os.path.exists(path):
        return []

    def drain() -> list[dict[str, Any]]:
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
        notices: list[dict[str, Any]] = []
        for line_number, line in enumerate(lines, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception as exc:
                raise ValueError(f"invalid companion inbox JSONL at line {line_number}: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"companion inbox JSONL at line {line_number} must be an object")
            notices.append(normalize_companion_notice(payload))
        atomic_write_text(path, "")
        return notices

    return run_with_interprocess_lock(path + ".lock", drain)


def normalize_companion_notice(notice: dict[str, Any]) -> dict[str, Any]:
    payload = dict(notice if isinstance(notice, dict) else {})
    payload["id"] = str(payload.get("id") or uuid.uuid4().hex)
    payload["created_at"] = str(payload.get("created_at") or now_text())
    payload["type"] = str(payload.get("type") or "node_review_notice")
    if payload["type"] not in NOTICE_TYPES:
        raise ValueError("companion notice type must be 'node_review_notice' or 'tool_failure_memory_notice'")
    source = payload.get("source")
    payload["source"] = dict(source) if isinstance(source, dict) else {}
    run = payload.get("run")
    payload["run"] = dict(run) if isinstance(run, dict) else {}
    report = payload.get("report")
    payload["report"] = dict(report) if isinstance(report, dict) else {}
    return payload


def format_companion_notice(notice: dict[str, Any]) -> str:
    payload = normalize_companion_notice(notice)
    if payload["type"] == "tool_failure_memory_notice":
        return _format_tool_failure_memory_notice(payload)
    return _format_node_review_notice(payload)


