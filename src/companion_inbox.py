from __future__ import annotations

import json
import os
import uuid
from typing import Any

from src.companion_notice_settings import companion_node_review_enabled
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
    if not companion_node_review_enabled():
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
    if payload["type"] != "node_review_notice":
        raise ValueError("companion notice type must be 'node_review_notice'")
    source = payload.get("source")
    payload["source"] = dict(source) if isinstance(source, dict) else {}
    run = payload.get("run")
    payload["run"] = dict(run) if isinstance(run, dict) else {}
    report = payload.get("report")
    payload["report"] = dict(report) if isinstance(report, dict) else {}
    return payload


def format_companion_notice(notice: dict[str, Any]) -> str:
    payload = normalize_companion_notice(notice)
    return _format_node_review_notice(payload)


def _format_node_review_notice(payload: dict[str, Any]) -> str:
    source = payload["source"]
    run = payload["run"]
    report = payload["report"]
    graph_id = str(source.get("graph_id") or "unknown").strip() or "unknown"
    node_id = str(source.get("node_id") or "unknown").strip() or "unknown"
    node_type_id = str(source.get("node_type_id") or "").strip()
    trace_id = str(run.get("trace_id") or "").strip()
    from_node = str(run.get("from_node") or "").strip()
    input_preview = str(run.get("input_preview") or "").strip()
    output_preview = str(run.get("output_preview") or "").strip()
    goal_status = str(run.get("goal_status") or "").strip()
    goal_reason = str(run.get("goal_reason") or "").strip()
    duration_ms = run.get("duration_ms")
    memory_path = str(report.get("memory_path") or "").strip()
    messages_path = str(report.get("messages_path") or "").strip()
    runtime_events_path = str(report.get("runtime_events_path") or "").strip()
    report_path = str(report.get("report_path") or "").strip()

    lines = [
        "A node run was persisted. Review the full persisted run and write a summary analysis report.",
        f"Node: {graph_id}/{node_id}",
    ]
    if node_type_id:
        lines.append(f"Node type: {node_type_id}")
    if trace_id:
        lines.append(f"Trace ID: {trace_id}")
    if from_node:
        lines.append(f"Triggered by node: {graph_id}/{from_node}")
    if duration_ms is not None:
        lines.append(f"Duration ms: {duration_ms}")
    if goal_status:
        lines.append(f"Goal status after run: {goal_status}")
    if goal_reason:
        lines.append(f"Goal reason: {goal_reason}")
    if memory_path:
        lines.append(f"Memory file: {memory_path}")
    if messages_path:
        lines.append(f"Structured messages file: {messages_path}")
    if runtime_events_path:
        lines.append(f"Runtime events file: {runtime_events_path}")
    if report_path:
        lines.append(f"Write report to: {report_path}")
    if input_preview:
        lines.append(f"Input preview: {input_preview}")
    if output_preview:
        lines.append(f"Output preview: {output_preview}")
    lines.extend(
        [
            "Report scope:",
            "- Reconstruct the run from the persisted messages and runtime events, including tool calls, tool results, and final answer.",
            "- Judge whether the requested result appears achieved, partially achieved, blocked, or not achieved.",
            "- Analyze optimization space from environment engineering, project code quality, and final answer quality.",
            "- Prefer concrete evidence and file paths over speculation. Keep suggestions scoped and actionable.",
            "- Save the report as Markdown at the report path above. Include a concise verdict, evidence, tool-call review, completion assessment, improvement opportunities, and recommended next actions.",
        ]
    )
    return "\n".join(lines)


