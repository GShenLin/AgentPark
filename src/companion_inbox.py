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


def _format_node_review_notice(payload: dict[str, Any]) -> str:
    source = payload["source"]
    run = payload["run"]
    report = payload["report"]
    memory = payload.get("memory")
    memory = dict(memory) if isinstance(memory, dict) else {}
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
    operational_memory_path = str(memory.get("operational_memory_path") or "").strip()
    memory_summary = str(memory.get("summary") or "").strip()
    memory_summary_error = str(memory.get("summary_error") or "").strip()
    memory_summary_chars = memory.get("summary_chars")
    summary_max_chars = memory.get("summary_max_chars")
    summary_max_items = memory.get("summary_max_items")
    snapshot_chars = memory.get("snapshot_chars")

    lines = [
        "A node run was persisted.",
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
    if operational_memory_path:
        lines.append(f"Operational memory file to edit when warranted: {operational_memory_path}")
    if messages_path:
        lines.append(f"Structured messages file: {messages_path}")
    if runtime_events_path:
        lines.append(f"Runtime events file: {runtime_events_path}")
    if memory_summary_chars is not None:
        lines.append(f"Current operational memory summary chars: {memory_summary_chars}")
    if snapshot_chars is not None:
        lines.append(f"Current operational memory JSON chars: {snapshot_chars}")
    if summary_max_chars is not None:
        lines.append(f"Future injected memory summary budget: max {summary_max_chars} chars")
    if summary_max_items is not None:
        lines.append(f"Future injected memory item budget: max {summary_max_items} active items")
    if memory_summary_error:
        lines.append(f"Operational memory summary read error: {memory_summary_error}")
    if memory_summary:
        lines.append(f"Current injected operational memory summary:\n{memory_summary}")
    if input_preview:
        lines.append(f"Input preview: {input_preview}")
    if output_preview:
        lines.append(f"Output preview: {output_preview}")
    lines.extend(
        [
            "Review scope:",
            "- Reconstruct the run from the persisted messages and runtime events, including tool calls, tool results, and final answer.",
            "- Judge whether the requested result appears achieved, partially achieved, blocked, or not achieved.",
            "- Analyze optimization space from environment engineering, project code quality, and final answer quality.",
            "- If the persisted run reveals a reusable behavior correction for this exact node, update the operational memory file above.",
            "- Keep operational memory entries short and scoped; they are summarized into future model input for this node.",
            "- Do not record one-off failures, transient network/provider problems, or broad advice that is not grounded in this persisted run.",
            "- Prefer concrete evidence and file paths over speculation. Keep suggestions scoped and actionable.",
            "- Do not write a separate review report unless the user explicitly asks for one.",
        ]
    )
    return "\n".join(lines)


def _format_tool_failure_memory_notice(payload: dict[str, Any]) -> str:
    source = payload["source"]
    run = payload["run"]
    report = payload["report"]
    failure = payload.get("failure")
    failure = dict(failure) if isinstance(failure, dict) else {}
    memory = payload.get("memory")
    memory = dict(memory) if isinstance(memory, dict) else {}
    context = payload.get("context")
    context = dict(context) if isinstance(context, dict) else {}

    graph_id = str(source.get("graph_id") or "unknown").strip() or "unknown"
    node_id = str(source.get("node_id") or "unknown").strip() or "unknown"
    node_type_id = str(source.get("node_type_id") or "").strip()
    provider = str(source.get("provider") or "").strip()
    memory_path = str(memory.get("operational_memory_path") or "").strip()
    memory_summary = str(memory.get("summary") or "").strip()
    memory_summary_error = str(memory.get("summary_error") or "").strip()
    memory_summary_chars = memory.get("summary_chars")
    summary_max_chars = memory.get("summary_max_chars")
    summary_max_items = memory.get("summary_max_items")
    snapshot_chars = memory.get("snapshot_chars")
    messages_path = str(report.get("messages_path") or "").strip()
    runtime_events_path = str(report.get("runtime_events_path") or "").strip()

    lines = [
        "A tool call failed in an Agent node. Review the context and update that node's operational memory only if the failure reveals a reusable correction.",
        f"Node: {graph_id}/{node_id}",
    ]
    if node_type_id:
        lines.append(f"Node type: {node_type_id}")
    if provider:
        lines.append(f"Provider: {provider}")
    trace_id = str(run.get("trace_id") or "").strip()
    if trace_id:
        lines.append(f"Trace ID: {trace_id}")
    tool_name = str(failure.get("tool_name") or "").strip()
    call_id = str(failure.get("call_id") or "").strip()
    status = str(failure.get("status") or "").strip()
    error = str(failure.get("error") or "").strip()
    if tool_name:
        lines.append(f"Failed tool: {tool_name}")
    if call_id:
        lines.append(f"Tool call ID: {call_id}")
    if status:
        lines.append(f"Failure status: {status}")
    if error:
        lines.append(f"Error: {error}")
    if memory_path:
        lines.append(f"Operational memory file to edit: {memory_path}")
    if messages_path:
        lines.append(f"Structured messages file: {messages_path}")
    if runtime_events_path:
        lines.append(f"Runtime events file: {runtime_events_path}")
    if memory_summary_chars is not None:
        lines.append(f"Current operational memory summary chars: {memory_summary_chars}")
    if snapshot_chars is not None:
        lines.append(f"Current operational memory JSON chars: {snapshot_chars}")
    if summary_max_chars is not None:
        lines.append(f"Future injected memory summary budget: max {summary_max_chars} chars")
    if summary_max_items is not None:
        lines.append(f"Future injected memory item budget: max {summary_max_items} active items")
    if memory_summary_error:
        lines.append(f"Operational memory summary read error: {memory_summary_error}")
    if memory_summary:
        lines.append(f"Current injected memory summary:\n{memory_summary}")

    result_preview = str(failure.get("result_preview") or "").strip()
    if result_preview:
        lines.append(f"Tool result preview:\n{result_preview}")
    recent_messages = context.get("recent_messages")
    if isinstance(recent_messages, list) and recent_messages:
        lines.append("Recent model context:")
        for item in recent_messages:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip() or "message"
            text = str(item.get("text") or "").strip()
            if text:
                lines.append(f"- {role}: {text}")

    lines.extend(
        [
            "Operational memory contract:",
            "- This memory is summarized and sent back into this node's model input on future runs and tool-call continuation contexts.",
            "- Keep entries short, scoped, and high signal; large memories make every future model call heavier.",
            "- Store only reusable corrections: tool argument shape, shell/platform constraint, provider limitation, repository convention, or recovery strategy.",
            "- Do not record transient provider/network failures, one-off typos, or raw logs.",
            "- If an existing memory is wrong or obsolete, resolve or replace it instead of adding a conflicting entry.",
            "Action:",
            "- Use the configured operational memory editing tool, if available, to edit exactly the operational memory file above.",
            "- If no update is warranted, call the tool with action=skip or leave the file unchanged and explain why.",
            "- Keep the resulting active memory summary within the stated character and item budgets.",
        ]
    )
    return "\n".join(lines)


