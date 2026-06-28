from __future__ import annotations

from typing import Any


MAX_RUNTIME_EVENTS = 20
MAX_RUNTIME_TOOL_CALLS = 20
RUNTIME_EVENT_TYPES = {"runtime_notice", "tool_call_start", "tool_call_end"}


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
