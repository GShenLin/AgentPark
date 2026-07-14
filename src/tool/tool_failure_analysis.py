from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any


DEFAULT_FAILURE_SAMPLE_LIMIT = 3


def build_tool_failure_analysis(records: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [record for record in records if isinstance(record, dict) and not bool(record.get("success"))]
    category_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    tool_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    status_tools: dict[str, set[str]] = defaultdict(set)

    for record in failures:
        tool_name = _tool_name(record)
        status = _failure_status(record)
        category_counts[_failure_category(record)] += 1
        status_counts[status] += 1
        status_tools[status].add(tool_name)
        tool_groups[tool_name].append(record)

    tools: dict[str, Any] = {}
    for tool_name, tool_records in sorted(tool_groups.items()):
        tools[tool_name] = {
            "tool_name": tool_name,
            "failure_count": len(tool_records),
            "categories": dict(Counter(_failure_category(record) for record in tool_records).most_common()),
            "statuses": dict(Counter(_failure_status(record) for record in tool_records).most_common()),
            "reasons": _reason_counts(tool_records),
            "samples": [_failure_sample(record) for record in tool_records[:DEFAULT_FAILURE_SAMPLE_LIMIT]],
        }

    shared_patterns = [
        {
            "category": f"status:{status}",
            "count": count,
            "tool_count": len(status_tools[status]),
            "tools": sorted(status_tools[status]),
        }
        for status, count in status_counts.most_common()
        if len(status_tools[status]) > 1
    ]
    categories = [
        {"category": category, "count": count}
        for category, count in category_counts.most_common()
    ]
    return {
        "analyzed_call_count": len(records),
        "total_failures": len(failures),
        "affected_tool_count": len(tool_groups),
        "categories": categories,
        "statuses": dict(status_counts.most_common()),
        "shared_patterns": shared_patterns,
        "tools": tools,
    }


def build_tool_failure_history(records: list[dict[str, Any]], tool_name: str) -> dict[str, Any]:
    safe_tool_name = str(tool_name or "").strip()
    if not safe_tool_name:
        raise ValueError("tool name is required")
    calls = [
        record
        for record in records
        if isinstance(record, dict)
        and not bool(record.get("success"))
        and _tool_name(record) == safe_tool_name
    ]
    return {
        "tool_name": safe_tool_name,
        "analyzed_call_count": len(records),
        "failure_count": len(calls),
        "calls": calls,
    }


def _failure_category(record: dict[str, Any]) -> str:
    status = _failure_status(record)
    payload = _result_object(record.get("result"))
    policy = str(payload.get("policy") or "").strip() if payload else ""
    if policy:
        return f"policy:{policy}"
    if status in {"timeout", "blocked", "stopped", "permission_denied", "locked", "locked_or_readonly"}:
        return status
    if status == "exception":
        return "exception"

    tool_name = _tool_name(record)
    if tool_name in {"execute_console_command", "execute_consoleCommand"}:
        return "process_exit" if _has_nonzero_returncode(payload) else "command_failed"
    if tool_name == "multi_tool_use_parallel":
        return "parallel_request_rejected"
    if tool_name == "apply_patch":
        return "patch_rejected"
    if tool_name == "read_file":
        return "read_failed"
    if tool_name in {"rg_list_files", "rg_search_text"}:
        return "search_failed"
    return status


def _reason_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    reasons = Counter(_failure_reason(record) for record in records)
    return dict(reasons.most_common())


def _failure_reason(record: dict[str, Any]) -> str:
    error = str(record.get("error") or "").strip()
    if error:
        return error
    payload = _result_object(record.get("result"))
    for key in ("reason", "error", "message", "stderr"):
        value = payload.get(key) if payload else None
        if value is not None and str(value).strip():
            return str(value).strip()
    return f"status:{_failure_status(record)}"


def _failure_sample(record: dict[str, Any]) -> dict[str, Any]:
    arguments = record.get("tool_call_arguments")
    command = ""
    if isinstance(arguments, dict) and "command" in arguments:
        command = str(arguments.get("command") or "").strip()
    return {
        "recorded_at": str(record.get("recorded_at") or "").strip(),
        "call_id": str(record.get("call_id") or "").strip(),
        "status": _failure_status(record),
        "category": _failure_category(record),
        "error": str(record.get("error") or "").strip(),
        "command": command,
        "arguments": arguments if isinstance(arguments, dict) else None,
        "result_preview": str(record.get("result_preview") or "").strip(),
    }


def _tool_name(record: dict[str, Any]) -> str:
    return str(record.get("tool_name") or "tool").strip() or "tool"


def _failure_status(record: dict[str, Any]) -> str:
    return str(record.get("status") or "failed").strip().lower() or "failed"


def _has_nonzero_returncode(payload: dict[str, Any] | None) -> bool:
    if not payload or isinstance(payload.get("returncode"), bool):
        return False
    return isinstance(payload.get("returncode"), int) and payload["returncode"] != 0


def _result_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
