from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from .runtime_paths import _get_graphs_dir
from .turn_audit_reader import (
    hydrate_runtime_record,
    iter_node_runtime_paths,
    read_jsonl,
    read_node_messages,
    read_tool_stats_for_calls,
    validate_component,
)
from .turn_audit_projection import project_turn_detail


@dataclass
class _Turn:
    trace_id: str
    graph_id: str
    node_id: str
    node_dir: str
    records: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""
    provider_id: str = ""
    status: str = "running"
    duration_ms: int | None = None
    error: str = ""
    local_call_ids: set[str] = field(default_factory=set)
    local_ended_ids: set[str] = field(default_factory=set)
    server_call_ids: set[str] = field(default_factory=set)
    server_ended_ids: set[str] = field(default_factory=set)


def list_turn_audits(
    *,
    start_date_text: str,
    end_date_text: str,
    graph_id: str = "",
    node_id: str = "",
    memories_root: str | None = None,
) -> dict[str, Any]:
    start_date = _validate_date(start_date_text, "start_date")
    end_date = _validate_date(end_date_text, "end_date")
    if start_date > end_date:
        raise ValueError("start_date must not be later than end_date")
    root = os.path.abspath(memories_root or _get_graphs_dir())
    selected_graph = validate_component(graph_id, "graph_id")
    selected_node = validate_component(node_id, "node_id")
    turns: list[dict[str, Any]] = []
    available_graph_ids: set[str] = set()
    available_node_ids: set[str] = set()

    for current_graph, current_node, runtime_path in iter_node_runtime_paths(root):
        available_graph_ids.add(current_graph)
        available_node_ids.add(current_node)
        if selected_graph and current_graph != selected_graph:
            continue
        if selected_node and current_node != selected_node:
            continue
        node_dir = os.path.dirname(runtime_path)
        states = _load_turns(runtime_path, current_graph, current_node)
        matching_states = [
            state
            for state in states.values()
            if start_date <= _turn_date(state) <= end_date
        ]
        message_dates = {
            str(record.get("ts") or "")[:10]
            for state in matching_states
            for record in state.records
            if len(str(record.get("ts") or "")) >= 10
        }
        messages = read_node_messages(node_dir, message_dates)
        messages_by_trace = _messages_by_trace(messages)
        for state in matching_states:
            trace_messages = messages_by_trace.get(state.trace_id, [])
            turns.append(_turn_summary(state, trace_messages))

    turns.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
    return {
        "ok": True,
        "start_date": start_date,
        "end_date": end_date,
        "memories_root": root,
        "available_graph_ids": sorted(available_graph_ids),
        "available_node_ids": sorted(available_node_ids),
        "turns": turns,
    }


def get_turn_audit(
    *,
    trace_id: str,
    graph_id: str,
    node_id: str,
    memories_root: str | None = None,
    tool_calls_path: str | None = None,
) -> dict[str, Any]:
    safe_trace = validate_component(trace_id, "trace_id", required=True)
    safe_graph = validate_component(graph_id, "graph_id", required=True)
    safe_node = validate_component(node_id, "node_id", required=True)
    root = os.path.abspath(memories_root or _get_graphs_dir())
    runtime_path = os.path.join(root, safe_graph, safe_node, "runtime_events.jsonl")
    if not os.path.isfile(runtime_path):
        raise FileNotFoundError("node runtime log not found")
    state = _load_turns(runtime_path, safe_graph, safe_node).get(safe_trace)
    if state is None:
        raise FileNotFoundError("turn audit trace not found")

    dates = {
        str(record.get("ts") or "")[:10]
        for record in state.records
        if len(str(record.get("ts") or "")) >= 10
    }
    messages = read_node_messages(state.node_dir, dates)
    trace_messages = [
        item for item in messages if str(item.get("trace_id") or "").strip() == safe_trace
    ]
    tool_stats = read_tool_stats_for_calls(
        state.local_call_ids,
        tool_calls_path=tool_calls_path,
    )
    projection = project_turn_detail(state, trace_messages, tool_stats)
    summary = _turn_summary(state, trace_messages)
    summary["file_change_count"] = len(projection["file_changes"])
    return {
        "ok": True,
        "turn": summary,
        "messages": trace_messages,
        **projection,
    }


def _load_turns(path: str, graph_id: str, node_id: str) -> dict[str, _Turn]:
    node_dir = os.path.dirname(path)
    turns: dict[str, _Turn] = {}
    for raw_record in read_jsonl(path):
        trace_id = str(raw_record.get("trace_id") or "").strip()
        if not trace_id:
            continue
        record = hydrate_runtime_record(raw_record, node_dir)
        turn = turns.setdefault(
            trace_id,
            _Turn(
                trace_id=trace_id,
                graph_id=graph_id,
                node_id=node_id,
                node_dir=node_dir,
            ),
        )
        turn.records.append(record)
        _apply_record(turn, record)
    return turns


def _apply_record(turn: _Turn, record: dict[str, Any]) -> None:
    timestamp = str(record.get("ts") or "").strip()
    event_name = str(record.get("event") or "").strip()
    event = record.get("runtime_event")
    event = event if isinstance(event, dict) else {}
    stage = str(event.get("stage") or "").strip()
    provider = str(event.get("provider") or "").strip()
    if provider:
        turn.provider_id = turn.provider_id or provider
    if stage == "node_run_start":
        turn.started_at = turn.started_at or timestamp
    elif stage == "node_run_summary":
        payload = _notice_payload(event)
        turn.completed_at = timestamp
        turn.status = str(payload.get("status") or "completed").strip().lower() or "completed"
        turn.duration_ms = _int_or_none(payload.get("duration_ms"))
        turn.error = str(payload.get("error") or "").strip()
    if not turn.started_at:
        turn.started_at = timestamp
    if event_name == "tool_call_start":
        call_id = str(event.get("call_id") or "").strip()
        if call_id:
            turn.local_call_ids.add(call_id)
    elif event_name == "tool_call_end":
        call_id = str(event.get("call_id") or "").strip()
        if call_id:
            turn.local_call_ids.add(call_id)
            turn.local_ended_ids.add(call_id)
    elif event_name == "server_tool_activity":
        call_id = str(event.get("call_id") or "").strip()
        status = str(event.get("status") or "").strip().lower()
        if call_id:
            turn.server_call_ids.add(call_id)
            if status in {"completed", "failed", "error", "cancelled", "timeout"}:
                turn.server_ended_ids.add(call_id)


def _turn_summary(turn: _Turn, messages: list[dict[str, Any]]) -> dict[str, Any]:
    user_messages = [item for item in messages if str(item.get("role") or "") == "user"]
    assistant_messages = [item for item in messages if str(item.get("role") or "") == "assistant"]
    question = _message_text(user_messages[0]) if user_messages else ""
    answer = _message_text(assistant_messages[-1]) if assistant_messages else _runtime_answer(turn)
    completeness = _completeness(turn, bool(question), bool(answer))
    return {
        "trace_id": turn.trace_id,
        "graph_id": turn.graph_id,
        "node_id": turn.node_id,
        "provider_id": turn.provider_id,
        "started_at": turn.started_at,
        "completed_at": turn.completed_at,
        "status": turn.status,
        "duration_ms": turn.duration_ms,
        "error": turn.error,
        "question": question,
        "answer_preview": answer[:500],
        "tool_call_count": len(turn.local_call_ids),
        "server_tool_call_count": len(turn.server_call_ids),
        "audit_completeness": completeness,
        "file_change_count": 0,
    }


def _messages_by_trace(messages: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for message in messages:
        trace_id = str(message.get("trace_id") or "").strip()
        if trace_id:
            output.setdefault(trace_id, []).append(message)
    return output


def _message_text(message: dict[str, Any]) -> str:
    parts = message.get("parts")
    if not isinstance(parts, list):
        return ""
    return "\n".join(
        str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict) and part.get("type") == "text"
    ).strip()


def _runtime_answer(turn: _Turn) -> str:
    for record in reversed(turn.records):
        if record.get("event") != "node_message_done":
            continue
        event = record.get("runtime_event")
        if isinstance(event, dict):
            return str(event.get("text_preview") or "")
    return ""


def _notice_payload(event: dict[str, Any]) -> dict[str, Any]:
    value = event.get("message_artifact", event.get("message"))
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _completeness(turn: _Turn, has_question: bool, has_answer: bool) -> str:
    if not turn.completed_at:
        return "running"
    tools_complete = turn.local_call_ids == turn.local_ended_ids
    server_tools_complete = turn.server_call_ids == turn.server_ended_ids
    return "complete" if has_question and has_answer and tools_complete and server_tools_complete else "partial"


def _turn_date(turn: _Turn) -> str:
    return str(turn.started_at or turn.completed_at)[:10]


def _validate_date(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError(f"{label} must use YYYY-MM-DD") from exc


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["get_turn_audit", "list_turn_audits"]
