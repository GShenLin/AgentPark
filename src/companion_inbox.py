from __future__ import annotations

import json
import os
import uuid
from typing import Any

from src.file_transaction import append_text
from src.file_transaction import atomic_write_text
from src.file_transaction import run_with_interprocess_lock
from src.message_protocol import now_text


COMPANION_GRAPH_ID = "companion"
COMPANION_INBOX_FILENAME = "inbox.jsonl"


def companion_config_path() -> str:
    from src.web_backend import runtime_paths

    return os.path.join(runtime_paths._get_graphs_dir(), COMPANION_GRAPH_ID, "config.json")


def companion_inbox_path(config_path: str = "") -> str:
    path = str(config_path or "").strip() or companion_config_path()
    if not path:
        return ""
    return os.path.join(os.path.dirname(path), COMPANION_INBOX_FILENAME)


def deliver_companion_notice(notice: dict[str, Any], *, config_path: str = "") -> bool:
    path = str(config_path or "").strip() or companion_config_path()
    if not path or not os.path.isfile(path):
        return False
    record = normalize_companion_notice(notice)
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
    payload["type"] = str(payload.get("type") or "operational_memory_notice")
    source = payload.get("source")
    payload["source"] = dict(source) if isinstance(source, dict) else {}
    issue = payload.get("issue")
    payload["issue"] = dict(issue) if isinstance(issue, dict) else {}
    memory = payload.get("memory")
    payload["memory"] = dict(memory) if isinstance(memory, dict) else {}
    return payload


def format_companion_notice(notice: dict[str, Any]) -> str:
    payload = normalize_companion_notice(notice)
    if payload.get("type") == "node_error_notice":
        return _format_node_error_notice(payload)
    return _format_operational_memory_notice(payload)


def _format_operational_memory_notice(payload: dict[str, Any]) -> str:
    source = payload["source"]
    issue = payload["issue"]
    memory = payload["memory"]
    graph_id = str(source.get("graph_id") or "unknown").strip() or "unknown"
    node_id = str(source.get("node_id") or "unknown").strip() or "unknown"
    provider = str(source.get("provider") or "").strip()
    tool_name = str(issue.get("tool_name") or "").strip()
    problem = _first_text(issue.get("error"), issue.get("evidence"), issue.get("title"), issue.get("reason"))
    action = str(memory.get("action") or "").strip()
    title = str(memory.get("title") or "").strip()
    lesson = str(memory.get("lesson") or "").strip()
    key = str(memory.get("key") or "").strip()

    lines = [
        "A node encountered the following issue. Determine whether project code changes are needed.",
        "If needed, update this model's prompt to improve the node's future runs.",
        f"Node: {graph_id}/{node_id}",
    ]
    if provider:
        lines.append(f"Provider: {provider}")
    if tool_name:
        lines.append(f"Tool: {tool_name}")
    if problem:
        lines.append(f"Issue: {problem}")
    if action:
        lines.append(f"Memory action: {action}")
    if title:
        lines.append(f"Memory title: {title}")
    if lesson:
        lines.append(f"Lesson: {lesson}")
    if key:
        lines.append(f"Memory key: {key}")
    return "\n".join(lines)


def _format_node_error_notice(payload: dict[str, Any]) -> str:
    source = payload["source"]
    issue = payload["issue"]
    recovery = payload.get("recovery") if isinstance(payload.get("recovery"), dict) else {}
    trigger = issue.get("trigger") if isinstance(issue.get("trigger"), dict) else {}
    graph_id = str(source.get("graph_id") or "unknown").strip() or "unknown"
    node_id = str(source.get("node_id") or "unknown").strip() or "unknown"
    node_type_id = str(source.get("node_type_id") or "").strip()
    from_node = str(trigger.get("from_node") or "").strip()
    trace_id = str(trigger.get("trace_id") or recovery.get("trace_id") or "").strip()
    input_preview = str(trigger.get("input") or recovery.get("original_input") or "").strip()
    error_text = _first_text(issue.get("error"), issue.get("message"))
    traceback_text = str(issue.get("traceback") or "").strip()

    lines = [
        "A node stopped working because it encountered an Error.",
        "This is an error notice. Determine whether project code changes are needed.",
        "If this is a project issue, fix the code, then restore the affected node so it can run again.",
        "After fixing, use companion graph/node tools to resume or rerun the affected node when appropriate.",
        f"Errored node: {graph_id}/{node_id}",
    ]
    if node_type_id:
        lines.append(f"Node type: {node_type_id}")
    if from_node:
        lines.append(f"Triggered by node: {graph_id}/{from_node}")
    if trace_id:
        lines.append(f"Trace ID: {trace_id}")
    if error_text:
        lines.append(f"Error: {error_text}")
    if input_preview:
        lines.append(f"Original input: {input_preview}")
    if traceback_text:
        lines.append(f"Traceback: {traceback_text}")
    return "\n".join(lines)


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
