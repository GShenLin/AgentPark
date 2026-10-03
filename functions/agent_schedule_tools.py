"""Agent-owned wakeup scheduling through the bound backend runtime."""
from __future__ import annotations

import json

from src.providers.agent_runtime_context import get_agent_runtime_context


_UNSET = object()


def manage_agent_schedule(
    action,
    prompt=_UNSET,
    run_at=_UNSET,
    delay_seconds=_UNSET,
    interval_seconds=_UNSET,
    idempotency_key=_UNSET,
    schedule_id=_UNSET,
    expected_revision=_UNSET,
    agent=None,
):
    """Forward only supplied fields; owner identity is bound by the backend."""
    try:
        callback = get_agent_runtime_context(agent).manage_schedule
        if not callable(callback):
            raise RuntimeError("Agent scheduling requires a bound backend runtime.")
        if action not in {"create", "list", "get", "update", "cancel"}:
            raise ValueError("action must be create, list, get, update, or cancel")
        params = {
            "prompt": prompt,
            "run_at": run_at,
            "delay_seconds": delay_seconds,
            "interval_seconds": interval_seconds,
            "idempotency_key": idempotency_key,
            "schedule_id": schedule_id,
            "expected_revision": expected_revision,
        }
        result = callback(action, **{key: value for key, value in params.items() if value is not _UNSET})
        if not isinstance(result, dict):
            raise TypeError("Agent scheduling backend must return an object.")
        return json.dumps({"status": "success", "result": result}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)


manage_agent_schedule_declaration = {
    "type": "function",
    "function": {
        "name": "manage_agent_schedule",
        "description": (
            "Create, inspect, update, or cancel durable wakeups for this Agent and its current task. "
            "A wakeup resumes the owning Agent with its configured conversation history and the stored prompt. "
            "For create, supply prompt, idempotency_key, and exactly one of run_at or delay_seconds. "
            "Use the same idempotency_key when retrying the same create request. "
            "Get requires schedule_id. Update and cancel require schedule_id and expected_revision "
            "from get/list. Updates preserve omitted fields; supply interval_seconds=null to clear "
            "recurrence. A repeating schedule requires interval_seconds of at least 60. "
            "Use list/get to inspect status rather than creating duplicate wakeups."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "list", "get", "update", "cancel"]},
                "prompt": {"type": "string", "minLength": 1, "description": "Instructions to execute when the Agent wakes."},
                "run_at": {"type": "string", "description": "Absolute ISO 8601 datetime with explicit timezone, such as 2026-10-03T12:00:00+08:00. Mutually exclusive with delay_seconds."},
                "delay_seconds": {"type": "number", "exclusiveMinimum": 0, "description": "Delay from now in seconds. Mutually exclusive with run_at."},
                "interval_seconds": {"type": ["number", "null"], "minimum": 60, "description": "Optional recurring interval; null clears recurrence on update."},
                "idempotency_key": {"type": "string", "minLength": 1, "description": "Required for create; unique within the owning task for this intended schedule."},
                "schedule_id": {"type": "string", "minLength": 1, "description": "Identifier returned by create/list/get."},
                "expected_revision": {"type": "integer", "minimum": 1, "description": "Current revision required for update/cancel; refetch after a conflict."},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}


__all__ = ["manage_agent_schedule", "manage_agent_schedule_declaration"]
