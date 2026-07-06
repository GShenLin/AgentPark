from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

from src.companion_inbox import deliver_companion_notice


def notify_companion_about_node_run(
    *,
    graph_id: str,
    node_id: str,
    node_type_id: str,
    trace_id: str,
    from_node: str = "",
    input_preview: str = "",
    output_preview: str = "",
    duration_ms: int | None = None,
    goal_result: dict[str, Any] | None = None,
    node_dir: str = "",
    memory_path: str = "",
    messages_path: str = "",
    runtime_events_path: str = "",
) -> bool:
    notice = build_node_run_review_notice(
        graph_id=graph_id,
        node_id=node_id,
        node_type_id=node_type_id,
        trace_id=trace_id,
        from_node=from_node,
        input_preview=input_preview,
        output_preview=output_preview,
        duration_ms=duration_ms,
        goal_result=goal_result,
        node_dir=node_dir,
        memory_path=memory_path,
        messages_path=messages_path,
        runtime_events_path=runtime_events_path,
    )
    if _is_companion_self_notice(notice):
        return False
    return deliver_companion_notice(notice)


def build_node_run_review_notice(
    *,
    graph_id: str,
    node_id: str,
    node_type_id: str,
    trace_id: str,
    from_node: str = "",
    input_preview: str = "",
    output_preview: str = "",
    duration_ms: int | None = None,
    goal_result: dict[str, Any] | None = None,
    node_dir: str = "",
    memory_path: str = "",
    messages_path: str = "",
    runtime_events_path: str = "",
) -> dict[str, Any]:
    source = {
        "graph_id": str(graph_id or "").strip(),
        "node_id": str(node_id or "").strip(),
        "node_type_id": str(node_type_id or "").strip(),
    }
    report_path = _review_report_path(
        node_dir=node_dir,
        graph_id=source["graph_id"],
        node_id=source["node_id"],
        trace_id=trace_id,
    )
    goal_state = _goal_state(goal_result)
    return {
        "type": "node_review_notice",
        "source": source,
        "run": {
            "trace_id": str(trace_id or "").strip(),
            "from_node": str(from_node or "").strip(),
            "input_preview": str(input_preview or "").strip(),
            "output_preview": str(output_preview or "").strip(),
            "duration_ms": duration_ms if isinstance(duration_ms, int) else None,
            "goal_status": str(goal_state.get("status") or "").strip(),
            "goal_reason": str(goal_state.get("reason") or "").strip(),
            "goal_should_continue": bool((goal_result or {}).get("should_continue"))
            if isinstance(goal_result, dict)
            else False,
        },
        "report": {
            "memory_path": str(memory_path or "").strip(),
            "messages_path": str(messages_path or "").strip(),
            "runtime_events_path": str(runtime_events_path or "").strip(),
            "report_path": report_path,
        },
    }


def _goal_state(goal_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(goal_result, dict):
        return {}
    state = goal_result.get("goal_state")
    if isinstance(state, dict):
        return state
    return {}


def _review_report_path(*, node_dir: str, graph_id: str, node_id: str, trace_id: str) -> str:
    base_dir = str(node_dir or "").strip()
    if not base_dir:
        return ""
    report_dir = os.path.join(base_dir, "reports")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    trace_part = _safe_filename_part(trace_id) or "run"
    graph_part = _safe_filename_part(graph_id) or "graph"
    node_part = _safe_filename_part(node_id) or "node"
    return os.path.join(report_dir, f"{stamp}-{graph_part}-{node_part}-{trace_part}.md")


def _safe_filename_part(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip(".-_")
    return text[:80]


def _is_companion_self_notice(notice: dict[str, Any]) -> bool:
    source = notice.get("source") if isinstance(notice, dict) else None
    if not isinstance(source, dict):
        return False
    graph_id = str(source.get("graph_id") or "").strip()
    node_id = str(source.get("node_id") or "").strip()
    return graph_id == "companion" and node_id == "companion"


__all__ = ["build_node_run_review_notice", "notify_companion_about_node_run"]
