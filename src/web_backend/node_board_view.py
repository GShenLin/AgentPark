from __future__ import annotations

import json
from copy import deepcopy
from typing import Any


BOARD_RUNTIME_FIELDS = {
    "state",
    "pending_count",
    "inflight",
    "_stop_requested",
    "node_event_seq",
    "last_message",
    "last_run_at",
    "last_runtime_event",
    "runtime_events",
    "runtime_tool_calls",
    "provider_request_summaries",
    "provider_request_totals",
    "goal",
    "goal_state",
}

BOARD_PERSISTENT_FIELDS = {
    "node_id",
    "graph_id",
    "type_id",
    "name",
    "input_num",
    "output_num",
    "ui",
    "private",
    "provider_id",
    "mode",
    "web_search",
    "thinking",
    "reasoning_effort",
    "instruction",
    "system_prompt",
    "plugins",
    "tools",
    "mcp_servers",
    "working_path",
    "remote_enabled",
    "remote_worker_id",
    "collaboration_mode",
    "_config_version",
}

BOARD_LAST_MESSAGE_MAX_CHARS = 512

_BOARD_PROVIDER_SUMMARY_FIELDS = {
    "request_index",
    "request_api",
    "responses_mode",
    "requested_responses_mode",
    "input_item_count",
    "approx_input_chars",
    "approx_input_tokens",
    "environment_context_chars",
    "tool_call_chars_total",
    "tool_result_chars_total",
    "tools_included_count",
}

_BOARD_TOOL_CALL_FIELDS = {
    "call_id",
    "name",
    "provider",
    "status",
    "duration_ms",
    "error",
    "result_chars",
    "result_preview_truncated",
    "diagnostics",
}

_BOARD_EVENT_FIELDS = {
    "type",
    "name",
    "call_id",
    "provider",
    "status",
    "duration_ms",
    "error",
    "result_chars",
    "result_preview_truncated",
    "diagnostics",
    "source",
    "stage",
    "message",
    "tool_type",
    "sources",
}


def build_node_board_view(config: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: deepcopy(config[key])
        for key in BOARD_PERSISTENT_FIELDS | BOARD_RUNTIME_FIELDS
        if key in config
    }
    last_message = result.get("last_message")
    if isinstance(last_message, str) and len(last_message) > BOARD_LAST_MESSAGE_MAX_CHARS:
        result["last_message"] = last_message[:BOARD_LAST_MESSAGE_MAX_CHARS]
    result["last_runtime_event"] = build_board_runtime_event(config.get("last_runtime_event"))
    result["runtime_events"] = _board_runtime_events(config.get("runtime_events"))
    result["runtime_tool_calls"] = _board_tool_calls(config.get("runtime_tool_calls"))
    summaries = config.get("provider_request_summaries")
    latest_summary = summaries[-1] if isinstance(summaries, list) and summaries else None
    compact_summary = build_board_provider_summary(latest_summary)
    result["provider_request_summaries"] = [compact_summary] if compact_summary else []
    return result


def build_board_provider_summary(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    summary = {
        key: deepcopy(value[key])
        for key in _BOARD_PROVIDER_SUMMARY_FIELDS
        if key in value
    }
    tool_results = value.get("tool_result_chars_by_call")
    if isinstance(tool_results, list):
        summary["tool_result_count"] = len(tool_results)
    largest_tool = value.get("largest_tool_result")
    if isinstance(largest_tool, dict):
        summary["largest_tool_result"] = {
            key: deepcopy(largest_tool[key])
            for key in ("name", "call_id", "chars", "status")
            if key in largest_tool
        }
    return summary


def build_board_runtime_event(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    event = {
        key: deepcopy(value[key])
        for key in _BOARD_EVENT_FIELDS
        if key in value
    }
    if str(event.get("type") or "").strip() != "runtime_notice":
        return event
    if str(event.get("stage") or "").strip() != "provider_request_summary":
        return event
    provider_summary = json.loads(str(event.get("message") or ""))
    if not isinstance(provider_summary, dict):
        raise ValueError("provider_request_summary runtime notice message must be a JSON object")
    compact_summary = build_board_provider_summary(provider_summary)
    event["message"] = json.dumps(compact_summary, ensure_ascii=False, separators=(",", ":"))
    return event


def _board_runtime_events(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    selected: dict[str, tuple[int, dict[str, Any]]] = {}
    for index, raw_event in enumerate(value):
        event = build_board_runtime_event(raw_event)
        if not event or str(event.get("type") or "").strip() != "runtime_notice":
            continue
        stage = str(event.get("stage") or "").strip()
        selected[stage or "runtime_notice"] = (index, event)
    return [event for _index, event in sorted(selected.values(), key=lambda item: item[0])]


def _board_tool_calls(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        {
            key: deepcopy(item[key])
            for key in _BOARD_TOOL_CALL_FIELDS
            if key in item
        }
        for item in value
        if isinstance(item, dict)
    ]


__all__ = [
    "BOARD_PERSISTENT_FIELDS",
    "BOARD_RUNTIME_FIELDS",
    "build_board_provider_summary",
    "build_board_runtime_event",
    "build_node_board_view",
]
