from __future__ import annotations

import json
import os
from typing import Any

from src.providers.provider_runtime_events import PROVIDER_REQUEST_SUMMARY_STAGE
from src.providers.provider_runtime_events import PROVIDER_REQUEST_COMPLETED_STAGE

from .node_runtime_event_sink import NODE_RUNTIME_EVENTS_FILENAME
from .runtime_event_store import (
    MAX_PROVIDER_REQUEST_SUMMARIES,
    MAX_RUNTIME_EVENTS,
    normalize_runtime_event,
    append_provider_request_completion,
    update_provider_request_totals,
)


MAX_RUNTIME_EVENT_PROJECTION_BYTES = 8 * 1024 * 1024


def load_node_runtime_projection(node_dir: str) -> dict[str, Any]:
    """Build the current UI diagnostics projection from the durable node event log."""
    path = os.path.join(str(node_dir or ""), NODE_RUNTIME_EVENTS_FILENAME)
    if not path or not os.path.isfile(path):
        return {}

    records = _read_recent_jsonl_records(path)
    runtime_events: list[dict[str, Any]] = []
    provider_summaries: list[dict[str, Any]] = []
    provider_totals_payload: dict[str, Any] = {}

    for record in records:
        event = record.get("runtime_event") if isinstance(record.get("runtime_event"), dict) else None
        if not isinstance(event, dict):
            continue
        try:
            normalized = normalize_runtime_event(event)
        except ValueError:
            continue
        runtime_events.append(normalized)
        if (
            normalized.get("type") == "runtime_notice"
            and str(normalized.get("stage") or "").strip() == PROVIDER_REQUEST_SUMMARY_STAGE
        ):
            summary = record.get("provider_request_summary")
            if not isinstance(summary, dict):
                summary = _parse_summary_from_notice(normalized)
            if isinstance(summary, dict):
                provider_summaries.append(summary)
                update_provider_request_totals(provider_totals_payload, summary)
        elif (
            normalized.get("type") == "runtime_notice"
            and str(normalized.get("stage") or "").strip() == PROVIDER_REQUEST_COMPLETED_STAGE
        ):
            completion = record.get("provider_request_completion")
            if not isinstance(completion, dict):
                completion = _parse_summary_from_notice(normalized)
            if isinstance(completion, dict):
                normalized["message"] = json.dumps(completion, ensure_ascii=False)
                append_provider_request_completion(provider_totals_payload, normalized)
                request_index = completion.get("request_index")
                usage = completion.get("usage")
                for summary in reversed(provider_summaries):
                    if isinstance(summary, dict) and summary.get("request_index") == request_index and isinstance(usage, dict):
                        summary["usage"] = dict(usage)
                        break

    projection: dict[str, Any] = {}
    if runtime_events:
        projection["runtime_events"] = runtime_events[-MAX_RUNTIME_EVENTS:]
        projection["last_runtime_event"] = runtime_events[-1]
    if provider_summaries:
        projection["provider_request_summaries"] = provider_summaries[-MAX_PROVIDER_REQUEST_SUMMARIES:]
    totals = provider_totals_payload.get("provider_request_totals")
    if isinstance(totals, dict):
        projection["provider_request_totals"] = totals
    return projection


def _read_recent_jsonl_records(path: str) -> list[dict[str, Any]]:
    size = os.path.getsize(path)
    start = max(0, size - MAX_RUNTIME_EVENT_PROJECTION_BYTES)
    with open(path, "rb") as handle:
        handle.seek(start)
        data = handle.read()
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if start > 0 and lines:
        lines = lines[1:]

    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _parse_summary_from_notice(event: dict[str, Any]) -> dict[str, Any] | None:
    try:
        payload = json.loads(str(event.get("message") or ""))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
