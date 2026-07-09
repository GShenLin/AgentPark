from __future__ import annotations

from typing import Any

from src.companion_inbox import deliver_companion_notice
from src.companion_paths import COMPANION_GRAPH_ID
from src.operational_memory_notice_context import build_operational_memory_notice_context


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
    if not _is_agent_node_notice(notice):
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
    goal_state = _goal_state(goal_result)
    memory_context = build_operational_memory_notice_context(
        node_dir=node_dir,
        memory_path=memory_path,
    )
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
        },
        "memory": memory_context,
    }


def _goal_state(goal_result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(goal_result, dict):
        return {}
    state = goal_result.get("goal_state")
    if isinstance(state, dict):
        return state
    return {}


def _is_companion_self_notice(notice: dict[str, Any]) -> bool:
    source = notice.get("source") if isinstance(notice, dict) else None
    if not isinstance(source, dict):
        return False
    graph_id = str(source.get("graph_id") or "").strip()
    return graph_id == COMPANION_GRAPH_ID


def _is_agent_node_notice(notice: dict[str, Any]) -> bool:
    source = notice.get("source") if isinstance(notice, dict) else None
    if not isinstance(source, dict):
        return False
    return str(source.get("node_type_id") or "").strip() == "agent_node"


__all__ = ["build_node_run_review_notice", "notify_companion_about_node_run"]
