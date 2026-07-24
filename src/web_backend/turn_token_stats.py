from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from src.providers.provider_request_usage import sanitize_provider_usage
from src.providers.provider_runtime_events import PROVIDER_REQUEST_COMPLETED_STAGE
from src.providers.provider_runtime_events import PROVIDER_REQUEST_SUMMARY_STAGE

from .runtime_paths import _get_graphs_dir


NODE_RUN_START_STAGE = "node_run_start"
NODE_RUN_SUMMARY_STAGE = "node_run_summary"
RUNTIME_EVENTS_FILENAME = "runtime_events.jsonl"
RECENT_TURNS_PER_PROVIDER = 20


@dataclass
class _TurnBuilder:
    trace_id: str
    graph_id: str = ""
    node_id: str = ""
    provider_id: str = ""
    started_at: str = ""
    completed_at: str = ""
    status: str = ""
    error: str = ""
    requests: dict[int, dict[str, Any]] = field(default_factory=dict)


@dataclass
class _RuntimeLogDiagnostic:
    path: str
    invalid_utf8_lines: list[int] = field(default_factory=list)
    invalid_json_lines: list[int] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any] | None:
        if not self.invalid_utf8_lines and not self.invalid_json_lines:
            return None
        return {
            "path": self.path,
            "invalid_utf8_lines": self.invalid_utf8_lines,
            "invalid_json_lines": self.invalid_json_lines,
        }


def load_turn_token_stats(
    memories_dir: str | None = None,
    *,
    graph_id: str = "",
    scope_hours: int = 0,
    reset_at: str = "",
) -> dict[str, Any]:
    root = os.path.abspath(memories_dir or _get_graphs_dir())
    selected_graph_id = str(graph_id or "").strip()
    cutoff = _latest_cutoff(_scope_cutoff(scope_hours), _parse_local_timestamp(reset_at))
    turns: list[dict[str, Any]] = []
    available_graph_ids: set[str] = set()
    diagnostics: list[dict[str, Any]] = []
    if os.path.isdir(root):
        for path in _runtime_event_paths(root):
            file_turns, diagnostic = _load_runtime_file_turns(path)
            available_graph_ids.update(
                str(turn.get("graph_id") or "").strip()
                for turn in file_turns
                if str(turn.get("graph_id") or "").strip()
            )
            turns.extend(
                turn
                for turn in file_turns
                if _turn_in_scope(turn, graph_id=selected_graph_id, cutoff=cutoff)
            )
            diagnostic_payload = diagnostic.to_payload()
            if diagnostic_payload is not None:
                diagnostics.append(diagnostic_payload)

    providers: dict[str, dict[str, Any]] = {}
    for turn in sorted(turns, key=lambda item: str(item.get("completed_at") or ""), reverse=True):
        provider_id = str(turn.get("provider_id") or "").strip()
        if not provider_id:
            continue
        provider = providers.setdefault(
            provider_id,
            {
                "provider_id": provider_id,
                "turn_count": 0,
                "usage_turn_count": 0,
                "missing_usage_turn_count": 0,
                "model_turn_count": 0,
                "usage_model_turn_count": 0,
                "recent_turns": [],
            },
        )
        provider["turn_count"] += 1
        provider["model_turn_count"] += int(turn.get("model_turn_count") or 0)
        provider["usage_model_turn_count"] += int(turn.get("usage_request_count") or 0)
        if turn.get("usage_status") == "available":
            provider["usage_turn_count"] += 1
        elif turn.get("usage_status") in {"missing", "partial"}:
            provider["missing_usage_turn_count"] += 1
        if len(provider["recent_turns"]) < RECENT_TURNS_PER_PROVIDER:
            provider["recent_turns"].append(turn)

    for provider in providers.values():
        recent_turns = provider["recent_turns"]
        provider["latest_turn"] = recent_turns[0] if recent_turns else None
    result: dict[str, Any] = {
        "providers": providers,
        "scope": {
            "graph_id": selected_graph_id,
            "hours": max(0, int(scope_hours or 0)),
            "reset_at": str(reset_at or "").strip(),
        },
        "available_graph_ids": sorted(available_graph_ids),
    }
    if diagnostics:
        result["diagnostics"] = diagnostics
    return result


def _runtime_event_paths(root: str) -> list[str]:
    paths: list[str] = []
    for current_dir, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name != "tool_artifacts"]
        if RUNTIME_EVENTS_FILENAME in filenames:
            paths.append(os.path.join(current_dir, RUNTIME_EVENTS_FILENAME))
    return sorted(paths)


def _load_runtime_file_turns(path: str) -> tuple[list[dict[str, Any]], _RuntimeLogDiagnostic]:
    builders: dict[str, _TurnBuilder] = {}
    diagnostic = _RuntimeLogDiagnostic(path=path)
    with open(path, "rb") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError:
                diagnostic.invalid_utf8_lines.append(line_number)
                continue
            record = _parse_record(line)
            if record is None:
                if line.strip():
                    diagnostic.invalid_json_lines.append(line_number)
                continue
            trace_id = str(record.get("trace_id") or "").strip()
            event = record.get("runtime_event")
            if not trace_id or not isinstance(event, dict):
                continue
            if str(event.get("type") or "").strip() != "runtime_notice":
                continue
            stage = str(event.get("stage") or "").strip()
            if stage not in {
                NODE_RUN_START_STAGE,
                PROVIDER_REQUEST_SUMMARY_STAGE,
                PROVIDER_REQUEST_COMPLETED_STAGE,
                NODE_RUN_SUMMARY_STAGE,
            }:
                continue
            builder = builders.setdefault(trace_id, _TurnBuilder(trace_id=trace_id))
            _apply_record(builder, record, event, stage)

    turns: list[dict[str, Any]] = []
    for builder in builders.values():
        turn = _finalize_turn(builder)
        if turn is not None:
            turns.append(turn)
    return turns, diagnostic


def _parse_record(line: str) -> dict[str, Any] | None:
    text = line.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _apply_record(builder: _TurnBuilder, record: dict[str, Any], event: dict[str, Any], stage: str) -> None:
    timestamp = str(record.get("ts") or event.get("event_time") or "").strip()
    builder.graph_id = builder.graph_id or str(record.get("graph_id") or "").strip()
    builder.node_id = builder.node_id or str(record.get("node_instance_id") or "").strip()
    provider_id = str(event.get("provider") or "").strip()
    if provider_id:
        builder.provider_id = provider_id

    if stage == NODE_RUN_START_STAGE:
        builder.started_at = builder.started_at or timestamp
        return
    if stage == NODE_RUN_SUMMARY_STAGE:
        payload = _parse_notice_payload(event.get("message")) or {}
        builder.completed_at = timestamp
        builder.status = str(payload.get("status") or "completed").strip().lower() or "completed"
        builder.error = str(payload.get("error") or "").strip()
        return

    payload_key = "provider_request_summary" if stage == PROVIDER_REQUEST_SUMMARY_STAGE else "provider_request_completion"
    payload = record.get(payload_key)
    if not isinstance(payload, dict):
        payload = _parse_notice_payload(event.get("message"))
    if not isinstance(payload, dict):
        return
    request_index = _non_negative_int(payload.get("request_index"))
    if request_index is None:
        return
    request = builder.requests.setdefault(request_index, {"request_index": request_index})
    if stage == PROVIDER_REQUEST_SUMMARY_STAGE:
        request["sent_at"] = timestamp
        return
    request["received_at"] = timestamp
    usage = sanitize_provider_usage(payload.get("usage"))
    if usage:
        request["usage"] = usage


def _parse_notice_payload(value: object) -> dict[str, Any] | None:
    try:
        payload = json.loads(str(value or ""))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _finalize_turn(builder: _TurnBuilder) -> dict[str, Any] | None:
    if not builder.completed_at or not builder.provider_id:
        return None
    requests = [request for _, request in sorted(builder.requests.items())]
    completed_requests = [
        request
        for request in requests
        if str(request.get("received_at") or "").strip()
    ]
    usage_requests = [
        request
        for request in completed_requests
        if isinstance(request.get("usage"), dict) and request.get("usage")
    ]
    usage_status = "not_requested" if not completed_requests else "missing"
    if usage_requests and len(usage_requests) == len(completed_requests):
        usage_status = "available"
    elif usage_requests:
        usage_status = "partial"

    cumulative = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    chart_points: list[dict[str, Any]] = [
        {
            "kind": "sent",
            "label": "Sent",
            "request_index": None,
            "at": builder.started_at or (str(completed_requests[0].get("sent_at") or "") if completed_requests else ""),
            "cumulative_input_tokens": 0,
            "cumulative_output_tokens": 0,
            "cumulative_total_tokens": 0,
            "request_input_tokens": None,
            "request_output_tokens": None,
        }
    ]
    normalized_requests: list[dict[str, Any]] = []
    for request in completed_requests:
        usage = dict(request.get("usage") or {})
        for key in cumulative:
            cumulative[key] += _non_negative_int(usage.get(key)) or 0
        normalized = {
            "request_index": request["request_index"],
            "sent_at": str(request.get("sent_at") or ""),
            "received_at": str(request.get("received_at") or ""),
            "usage": usage,
            "cumulative_input_tokens": cumulative["input_tokens"],
            "cumulative_output_tokens": cumulative["output_tokens"],
            "cumulative_total_tokens": cumulative["total_tokens"],
        }
        normalized_requests.append(normalized)
        chart_points.append(
            {
                "kind": "response",
                "label": f"Reply {request['request_index']}",
                "request_index": request["request_index"],
                "at": normalized["received_at"],
                "cumulative_input_tokens": cumulative["input_tokens"],
                "cumulative_output_tokens": cumulative["output_tokens"],
                "cumulative_total_tokens": cumulative["total_tokens"],
                "request_input_tokens": _non_negative_int(usage.get("input_tokens")),
                "request_output_tokens": _non_negative_int(usage.get("output_tokens")),
            }
        )

    chart_points.append(
        {
            "kind": "terminal",
            "label": "Completed" if builder.status == "completed" else builder.status.title(),
            "request_index": None,
            "at": builder.completed_at,
            "cumulative_input_tokens": cumulative["input_tokens"],
            "cumulative_output_tokens": cumulative["output_tokens"],
            "cumulative_total_tokens": cumulative["total_tokens"],
            "request_input_tokens": None,
            "request_output_tokens": None,
        }
    )
    return {
        "trace_id": builder.trace_id,
        "graph_id": builder.graph_id,
        "node_id": builder.node_id,
        "provider_id": builder.provider_id,
        "started_at": builder.started_at,
        "completed_at": builder.completed_at,
        "persisted_at": builder.completed_at if builder.status == "completed" else "",
        "status": builder.status,
        "error": builder.error,
        "request_count": len(requests),
        "model_turn_count": len(completed_requests),
        "incomplete_request_count": max(0, len(requests) - len(completed_requests)),
        "usage_request_count": len(usage_requests),
        "missing_usage_request_count": max(0, len(completed_requests) - len(usage_requests)),
        "usage_status": usage_status,
        "first_response": normalized_requests[0] if normalized_requests else None,
        "accumulated_usage": dict(cumulative),
        "persisted_totals": dict(cumulative),
        "requests": normalized_requests,
        "chart_points": chart_points,
    }


def _scope_cutoff(scope_hours: int) -> datetime | None:
    try:
        hours = int(scope_hours or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("scope_hours must be an integer") from exc
    if hours <= 0:
        return None
    return datetime.now().astimezone().replace(tzinfo=None) - timedelta(hours=hours)


def _turn_in_scope(turn: dict[str, Any], *, graph_id: str, cutoff: datetime | None) -> bool:
    if graph_id and str(turn.get("graph_id") or "").strip() != graph_id:
        return False
    if cutoff is None:
        return True
    completed_at = _parse_local_timestamp(turn.get("completed_at"))
    return completed_at is not None and completed_at > cutoff


def _latest_cutoff(first: datetime | None, second: datetime | None) -> datetime | None:
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)


def _parse_local_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None
