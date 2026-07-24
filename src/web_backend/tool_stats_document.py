from __future__ import annotations

from src.tool.tool_failure_analysis import build_tool_failure_analysis, build_tool_failure_history
from src.tool.tool_stats_store import build_tool_stats_summary, load_all_tool_call_stats, load_tool_stats_reset_at

from .tool_stats_scope import available_tool_graph_ids, filter_tool_call_records
from .turn_token_stats import load_turn_token_stats


def build_scoped_tool_stats_document(*, graph_id: str = "", scope_hours: int = 0) -> dict:
    reset_at = load_tool_stats_reset_at()
    all_calls = load_all_tool_call_stats()
    scoped_calls = filter_tool_call_records(
        all_calls,
        graph_id=graph_id,
        scope_hours=scope_hours,
    )
    recent_calls_by_provider: dict[str, list[dict]] = {}
    analysis_calls_by_provider: dict[str, list[dict]] = {}
    for call in scoped_calls:
        provider_id = str(call.get("provider_id") or "unknown").strip() or "unknown"
        recent = recent_calls_by_provider.setdefault(provider_id, [])
        if len(recent) < 50:
            recent.append(call)
        analysis_calls_by_provider.setdefault(provider_id, []).append(call)

    turn_stats = load_turn_token_stats(
        graph_id=graph_id,
        scope_hours=scope_hours,
        reset_at=reset_at,
    )
    available_graph_ids = sorted(
        set(available_tool_graph_ids(all_calls))
        | set(turn_stats.get("available_graph_ids") or [])
    )
    return {
        "summary": build_tool_stats_summary(scoped_calls),
        "recent_calls": scoped_calls[:50],
        "recent_calls_by_provider": recent_calls_by_provider,
        "failure_analysis": build_tool_failure_analysis(scoped_calls),
        "failure_analysis_by_provider": {
            provider_id: build_tool_failure_analysis(calls)
            for provider_id, calls in analysis_calls_by_provider.items()
        },
        "turn_stats": turn_stats,
        "scope": {
            "graph_id": str(graph_id or "").strip(),
            "hours": max(0, int(scope_hours or 0)),
            "reset_at": reset_at,
            "available_graph_ids": available_graph_ids,
        },
    }


def build_scoped_tool_failure_history(
    tool_name: str,
    *,
    graph_id: str = "",
    scope_hours: int = 0,
) -> dict:
    calls = filter_tool_call_records(
        load_all_tool_call_stats(),
        graph_id=graph_id,
        scope_hours=scope_hours,
    )
    return build_tool_failure_history(calls, tool_name)
