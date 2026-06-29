from __future__ import annotations

from typing import Any

from src.companion_inbox import deliver_companion_notice


def notify_companion_about_node_error(
    *,
    graph_id: str,
    node_id: str,
    node_type_id: str,
    error: str,
    error_message: str,
    trigger: dict[str, Any] | None = None,
    traceback_text: str = "",
) -> bool:
    notice = build_node_error_notice(
        graph_id=graph_id,
        node_id=node_id,
        node_type_id=node_type_id,
        error=error,
        error_message=error_message,
        trigger=trigger,
        traceback_text=traceback_text,
    )
    try:
        return deliver_companion_notice(notice)
    except Exception:
        return False


def build_node_error_notice(
    *,
    graph_id: str,
    node_id: str,
    node_type_id: str,
    error: str,
    error_message: str,
    trigger: dict[str, Any] | None = None,
    traceback_text: str = "",
) -> dict[str, Any]:
    safe_trigger = dict(trigger) if isinstance(trigger, dict) else {}
    return {
        "type": "node_error_notice",
        "source": {
            "graph_id": str(graph_id or "").strip(),
            "node_id": str(node_id or "").strip(),
            "node_type_id": str(node_type_id or "").strip(),
        },
        "issue": {
            "kind": "node_error",
            "error": str(error or "").strip(),
            "message": str(error_message or "").strip(),
            "traceback": _preview_text(traceback_text, 4000),
            "trigger": safe_trigger,
        },
        "recovery": {
            "instruction": (
                "This is a node Error notice. Determine whether the Error is caused by project code. "
                "If it is a project issue, fix the code first, then restore the affected node so it can run again."
            ),
            "graph_id": str(graph_id or "").strip(),
            "node_id": str(node_id or "").strip(),
            "original_input": str(safe_trigger.get("input") or "").strip(),
            "trace_id": str(safe_trigger.get("trace_id") or "").strip(),
        },
    }


def _preview_text(value: object, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


__all__ = ["build_node_error_notice", "notify_companion_about_node_error"]
