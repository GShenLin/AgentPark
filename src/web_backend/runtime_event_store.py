from __future__ import annotations

import json
from typing import Any

from src.providers.provider_runtime_events import PROVIDER_REQUEST_SUMMARY_STAGE
from src.providers.provider_runtime_events import PROVIDER_REQUEST_COMPLETED_STAGE
from src.providers.provider_request_usage import add_provider_usage_totals
from src.providers.provider_request_usage import sanitize_provider_usage


MAX_RUNTIME_EVENTS = 20
MAX_RUNTIME_TOOL_CALLS = 20
MAX_PROVIDER_REQUEST_SUMMARIES = 8
RUNTIME_EVENT_TYPES = {"runtime_notice", "tool_call_start", "tool_call_end", "server_tool_activity"}


def normalize_runtime_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("runtime event must be an object")

    event_type = str(event.get("type") or "").strip().lower()
    if event_type not in RUNTIME_EVENT_TYPES:
        raise ValueError(f"unsupported runtime event type: {event_type or '<empty>'}")

    if event_type == "runtime_notice":
        message = str(event.get("message") or "").strip()
        if not message:
            raise ValueError("runtime_notice requires message")
        normalized: dict[str, Any] = {
            "type": "runtime_notice",
            "message": message,
            "source": str(event.get("source") or "runtime").strip() or "runtime",
        }
        for key in ("stage", "name", "call_id", "provider"):
            value = str(event.get(key) or "").strip()
            if value:
                normalized[key] = value
        _copy_event_timestamps(normalized, event)
        return normalized

    if event_type == "server_tool_activity":
        call_id = str(event.get("call_id") or "").strip()
        tool_type = str(event.get("tool_type") or "").strip().lower()
        if not call_id or not tool_type:
            raise ValueError("server_tool_activity requires call_id and tool_type")
        normalized = {
            "type": event_type,
            "call_id": call_id,
            "tool_type": tool_type,
            "status": str(event.get("status") or "in_progress").strip().lower() or "in_progress",
        }
        provider = str(event.get("provider") or "").strip()
        if provider:
            normalized["provider"] = provider
        action = event.get("action")
        if isinstance(action, dict) and action:
            normalized["action"] = dict(action)
        sources = event.get("sources")
        if isinstance(sources, list) and sources:
            normalized["sources"] = [dict(item) for item in sources if isinstance(item, dict)]
        details = event.get("details")
        if isinstance(details, dict) and details:
            normalized["details"] = dict(details)
        error = str(event.get("error") or "").strip()
        if error:
            normalized["error"] = error
        _copy_event_timestamps(normalized, event)
        return normalized

    call_id = str(event.get("call_id") or "").strip()
    if not call_id:
        raise ValueError("tool runtime event requires call_id")

    name = str(event.get("name") or "tool").strip() or "tool"
    normalized = {
        "type": event_type,
        "name": name,
        "call_id": call_id,
    }
    provider = str(event.get("provider") or "").strip()
    if provider:
        normalized["provider"] = provider
    _copy_event_timestamps(normalized, event)

    arguments = event.get("arguments")
    if isinstance(arguments, dict):
        normalized["arguments"] = dict(arguments)

    if event_type == "tool_call_end":
        normalized["status"] = str(event.get("status") or "completed").strip() or "completed"
        duration_ms = _normalize_non_negative_rounded_int(event.get("duration_ms"))
        if duration_ms is not None:
            normalized["duration_ms"] = duration_ms
        error = str(event.get("error") or "").strip()
        if error:
            normalized["error"] = error
        result_preview = str(event.get("result_preview") or "").strip()
        if result_preview:
            normalized["result_preview"] = result_preview
        if "result_chars" in event:
            result_chars = _normalize_non_negative_rounded_int(event.get("result_chars"))
            if result_chars is not None:
                normalized["result_chars"] = result_chars
        if "result_preview_truncated" in event:
            normalized["result_preview_truncated"] = bool(event.get("result_preview_truncated"))
        result_tail_preview = str(event.get("result_tail_preview") or "").strip()
        if result_tail_preview:
            normalized["result_tail_preview"] = result_tail_preview
        if "result_tail_preview_truncated" in event:
            normalized["result_tail_preview_truncated"] = bool(event.get("result_tail_preview_truncated"))
        diagnostics = _normalize_diagnostics(event.get("diagnostics"))
        if diagnostics:
            normalized["diagnostics"] = diagnostics
        memory_persistence_warning = str(event.get("memory_persistence_warning") or "").strip()
        if memory_persistence_warning:
            normalized["memory_persistence_warning"] = memory_persistence_warning

    return normalized


def _normalize_non_negative_rounded_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return None


def _normalize_diagnostics(value: Any) -> list[str] | None:
    if not isinstance(value, (list, tuple)):
        return None
    diagnostics = [str(item).strip() for item in value if item is not None and str(item).strip()]
    return diagnostics or None


def append_runtime_event(payload: dict[str, Any], event: dict[str, Any]) -> None:
    normalized = normalize_runtime_event(event)
    payload["last_runtime_event"] = normalized
    history = payload.get("runtime_events")
    if not isinstance(history, list):
        history = []
    history.append(normalized)
    payload["runtime_events"] = history[-MAX_RUNTIME_EVENTS:]
    upsert_runtime_tool_call(payload, normalized)
    append_provider_request_summary(payload, normalized)
    append_provider_request_completion(payload, normalized)


def upsert_runtime_tool_call(payload: dict[str, Any], event: dict[str, Any]) -> None:
    event_type = str(event.get("type") or "").strip()
    if event_type not in {"tool_call_start", "tool_call_end"}:
        return

    call_id = str(event.get("call_id") or "").strip()
    if not call_id:
        raise ValueError("tool runtime event requires call_id")

    calls = payload.get("runtime_tool_calls")
    if not isinstance(calls, list):
        calls = []

    existing = None
    for item in calls:
        if isinstance(item, dict) and str(item.get("call_id") or "").strip() == call_id:
            existing = item
            break

    if existing is None:
        existing = {
            "call_id": call_id,
            "name": str(event.get("name") or "tool").strip() or "tool",
            "provider": str(event.get("provider") or "").strip() or None,
            "arguments": event.get("arguments") if isinstance(event.get("arguments"), dict) else None,
            "status": "running",
            "duration_ms": None,
            "error": None,
            "result_preview": None,
            "result_chars": None,
            "result_preview_truncated": None,
            "result_tail_preview": None,
            "result_tail_preview_truncated": None,
            "diagnostics": None,
            "memory_persistence_warning": None,
            "started_event_time": None,
            "started_monotonic_ns": None,
            "completed_event_time": None,
            "completed_monotonic_ns": None,
        }
        calls.append(existing)

    name = str(event.get("name") or "").strip()
    if name:
        existing["name"] = name
    if event.get("provider") is not None:
        provider = str(event.get("provider") or "").strip()
        existing["provider"] = provider or None
    if isinstance(event.get("arguments"), dict):
        existing["arguments"] = dict(event["arguments"])

    if event_type == "tool_call_start":
        existing["status"] = "running"
        existing["started_event_time"] = event.get("event_time") or existing.get("started_event_time")
        existing["started_monotonic_ns"] = event.get("monotonic_ns") or existing.get("started_monotonic_ns")
    else:
        existing["status"] = str(event.get("status") or "completed").strip() or "completed"
        existing["completed_event_time"] = event.get("event_time") or existing.get("completed_event_time")
        existing["completed_monotonic_ns"] = event.get("monotonic_ns") or existing.get("completed_monotonic_ns")
        existing["duration_ms"] = event.get("duration_ms") if isinstance(event.get("duration_ms"), int) else None
        existing["error"] = str(event.get("error") or "").strip() or None
        existing["result_preview"] = str(event.get("result_preview") or "").strip() or None
        existing["result_chars"] = event.get("result_chars") if isinstance(event.get("result_chars"), int) else None
        if "result_preview_truncated" in event:
            existing["result_preview_truncated"] = bool(event.get("result_preview_truncated"))
        else:
            existing["result_preview_truncated"] = None
        existing["result_tail_preview"] = str(event.get("result_tail_preview") or "").strip() or None
        if "result_tail_preview_truncated" in event:
            existing["result_tail_preview_truncated"] = bool(event.get("result_tail_preview_truncated"))
        else:
            existing["result_tail_preview_truncated"] = None
        diagnostics = event.get("diagnostics")
        existing["diagnostics"] = [str(item) for item in diagnostics] if isinstance(diagnostics, list) else None
        existing["memory_persistence_warning"] = str(event.get("memory_persistence_warning") or "").strip() or None

    payload["runtime_tool_calls"] = calls[-MAX_RUNTIME_TOOL_CALLS:]


def append_provider_request_summary(payload: dict[str, Any], event: dict[str, Any]) -> None:
    if str(event.get("type") or "").strip() != "runtime_notice":
        return
    if str(event.get("stage") or "").strip() != PROVIDER_REQUEST_SUMMARY_STAGE:
        return
    message = str(event.get("message") or "").strip()
    if not message:
        return
    try:
        summary = json.loads(message)
    except Exception:
        return
    if not isinstance(summary, dict):
        return
    sanitized = _sanitize_provider_request_summary(summary)
    update_provider_request_totals(payload, sanitized)
    summaries = payload.get("provider_request_summaries")
    if not isinstance(summaries, list):
        summaries = []
    summaries.append(sanitized)
    payload["provider_request_summaries"] = summaries[-MAX_PROVIDER_REQUEST_SUMMARIES:]


def update_provider_request_totals(payload: dict[str, Any], summary: dict[str, Any]) -> None:
    totals = payload.get("provider_request_totals")
    if not isinstance(totals, dict):
        totals = {
            "request_count": 0,
            "approx_input_chars": 0,
            "approx_input_tokens": 0,
            "tool_call_chars": 0,
            "tool_result_chars": 0,
        }
    totals["request_count"] = _normalize_non_negative_int(totals.get("request_count")) or 0
    totals["approx_input_chars"] = _normalize_non_negative_int(totals.get("approx_input_chars")) or 0
    totals["approx_input_tokens"] = _normalize_non_negative_int(totals.get("approx_input_tokens")) or 0
    totals["tool_call_chars"] = _normalize_non_negative_int(totals.get("tool_call_chars")) or 0
    totals["tool_result_chars"] = _normalize_non_negative_int(totals.get("tool_result_chars")) or 0

    totals["request_count"] += 1
    totals["approx_input_chars"] += _summary_chars(summary, "approx_input_chars")
    totals["approx_input_tokens"] += _summary_chars(summary, "approx_input_tokens")
    totals["tool_call_chars"] += _summary_chars(summary, "tool_call_chars_total")
    totals["tool_result_chars"] += _summary_chars(summary, "tool_result_chars_total")
    request_index = _normalize_non_negative_int(summary.get("request_index"))
    if request_index is not None:
        totals["last_request_index"] = request_index
    payload["provider_request_totals"] = totals


def append_provider_request_completion(payload: dict[str, Any], event: dict[str, Any]) -> None:
    if str(event.get("type") or "").strip() != "runtime_notice":
        return
    if str(event.get("stage") or "").strip() != PROVIDER_REQUEST_COMPLETED_STAGE:
        return
    completion = _parse_provider_request_payload(event.get("message"))
    if completion is None:
        return
    request_index = _normalize_non_negative_int(completion.get("request_index"))
    usage = sanitize_provider_usage(completion.get("usage"))
    if request_index is None or not usage:
        return
    summaries = payload.get("provider_request_summaries")
    if isinstance(summaries, list):
        for summary in reversed(summaries):
            if isinstance(summary, dict) and _normalize_non_negative_int(summary.get("request_index")) == request_index:
                summary["usage"] = dict(usage)
                break
    totals = payload.get("provider_request_totals")
    if not isinstance(totals, dict):
        totals = {}
    add_provider_usage_totals(totals, usage)
    totals["last_completed_request_index"] = request_index
    payload["provider_request_totals"] = totals


def _parse_provider_request_payload(value: object) -> dict[str, Any] | None:
    message = str(value or "").strip()
    if not message:
        return None
    try:
        payload = json.loads(message)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _copy_event_timestamps(normalized: dict[str, Any], event: dict[str, Any]) -> None:
    event_time = str(event.get("event_time") or "").strip()
    if event_time:
        normalized["event_time"] = event_time
    monotonic_ns = _normalize_non_negative_int(event.get("monotonic_ns"))
    if monotonic_ns is not None:
        normalized["monotonic_ns"] = monotonic_ns


def _normalize_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def clear_runtime_event(payload: dict[str, Any], *, reset_history: bool = False) -> None:
    payload.pop("last_runtime_event", None)
    if reset_history:
        payload.pop("runtime_events", None)
        payload.pop("runtime_tool_calls", None)
        payload.pop("provider_request_summaries", None)
        payload.pop("provider_request_totals", None)


def _sanitize_provider_request_summary(summary: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "request_index",
        "request_api",
        "responses_mode",
        "requested_responses_mode",
        "instructions_present",
        "instructions_chars",
        "input_item_count",
        "approx_input_chars",
        "approx_input_tokens",
        "environment_context_chars",
        "turn_context_chars",
        "permissions_context_chars",
        "collaboration_context_chars",
        "internal_context_chars",
        "skills_context_chars",
        "mcp_servers_context_chars",
        "operational_memory_context_chars",
        "project_instructions_context_chars",
        "input_items",
        "largest_input_items",
        "tool_call_chars_by_call",
        "tool_call_chars_total",
        "tool_result_chars_by_call",
        "tool_result_chars_total",
        "largest_tool_result",
        "tools_included",
        "tools_included_count",
        "stream",
        "usage",
        "context_item_hash",
        "context_update_mode",
        "context_diff_paths",
        "persistent_context_item_hash",
        "persistent_context_update_mode",
        "payload_log_path",
        "payload_log_error",
    }
    sanitized = {key: summary.get(key) for key in allowed if key in summary}
    for key in ("input_items", "largest_input_items", "tool_call_chars_by_call", "tool_result_chars_by_call", "tools_included"):
        value = sanitized.get(key)
        if isinstance(value, list):
            sanitized[key] = value[:20]
    return sanitized


def _summary_chars(summary: dict[str, Any], key: str) -> int:
    value = _normalize_non_negative_int(summary.get(key))
    return value if value is not None else 0
