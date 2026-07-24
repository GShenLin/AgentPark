from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def filter_tool_call_records(
    records: list[dict[str, Any]],
    *,
    graph_id: str = "",
    scope_hours: int = 0,
) -> list[dict[str, Any]]:
    selected_graph_id = str(graph_id or "").strip()
    cutoff = scope_cutoff(scope_hours)
    return [
        record
        for record in records
        if _record_in_scope(record, graph_id=selected_graph_id, cutoff=cutoff)
    ]


def available_tool_graph_ids(records: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(record.get("graph_id") or "").strip()
            for record in records
            if str(record.get("graph_id") or "").strip()
        }
    )


def scope_cutoff(scope_hours: int) -> datetime | None:
    try:
        hours = int(scope_hours or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("scope_hours must be an integer") from exc
    if hours <= 0:
        return None
    return datetime.now().astimezone().replace(tzinfo=None) - timedelta(hours=hours)


def _record_in_scope(record: dict[str, Any], *, graph_id: str, cutoff: datetime | None) -> bool:
    if graph_id and str(record.get("graph_id") or "").strip() != graph_id:
        return False
    if cutoff is None:
        return True
    recorded_at = _parse_local_timestamp(record.get("recorded_at"))
    return recorded_at is not None and recorded_at >= cutoff


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
