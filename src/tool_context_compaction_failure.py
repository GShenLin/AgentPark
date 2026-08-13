from __future__ import annotations

import json


SUCCESS_EXECUTION_STATUSES = {"", "ok", "done", "success", "completed"}
SUCCESS_PAYLOAD_STATUSES = {"ok", "success", "completed"}
MAX_FAILURE_REASON_CHARS = 2000


def describe_tool_context_compaction_failure(
    execution: object,
    *,
    applied: bool,
    changed: bool,
) -> str:
    execution_error = _execution_field(execution, "error")
    if execution_error:
        return _limit_failure_reason(execution_error)

    cleaned_result = _execution_value(execution, "cleaned_result")
    payload = _parse_result_payload(cleaned_result)
    if isinstance(payload, dict):
        payload_error = str(payload.get("error") or "").strip()
        if payload_error:
            return _limit_failure_reason(payload_error)
        payload_status = str(payload.get("status") or "").strip()
        if payload_status and payload_status.lower() not in SUCCESS_PAYLOAD_STATUSES:
            return _limit_failure_reason(
                f"compact_tool_context returned status={payload_status} without applying a context change"
            )
        if payload.get("changed") is False:
            return (
                "compact_tool_context reported changed=false; remove or rewrite at least one eligible "
                "tool-context message"
            )

    execution_status = _execution_field(execution, "status") or "completed"
    if execution_status.lower() not in SUCCESS_EXECUTION_STATUSES:
        return "compact_tool_context execution failed without a specific error"
    if not applied:
        return "compact_tool_context completed without applying a compaction decision"
    if not changed:
        return "compact_tool_context did not remove or rewrite any eligible tool-context message"
    return "compact_tool_context did not complete the active context-compaction checkpoint"


def _execution_field(execution: object, field: str) -> str:
    return str(_execution_value(execution, field) or "").strip()


def _execution_value(execution: object, field: str) -> object:
    if isinstance(execution, dict):
        return execution.get(field)
    return getattr(execution, field, None)


def _parse_result_payload(cleaned_result: object) -> object:
    if isinstance(cleaned_result, dict):
        return cleaned_result
    if not isinstance(cleaned_result, str) or not cleaned_result.strip():
        return None
    try:
        return json.loads(cleaned_result)
    except (TypeError, ValueError):
        return None


def _limit_failure_reason(reason: str) -> str:
    normalized = " ".join(str(reason or "").split())
    return normalized if len(normalized) <= MAX_FAILURE_REASON_CHARS else f"{normalized[:1997]}..."


__all__ = ["describe_tool_context_compaction_failure"]
