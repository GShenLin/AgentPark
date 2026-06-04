from __future__ import annotations

from typing import Any

from .shared import now_text


def build_tool_call_history_envelope(event: dict[str, Any]) -> dict[str, Any]:
    call_id = str(event.get("call_id") or "").strip()
    name = str(event.get("name") or "tool").strip() or "tool"
    if not call_id:
        raise ValueError("tool history entry requires call_id")

    part: dict[str, Any] = {
        "type": "tool_call",
        "call_id": call_id,
        "name": name,
        "provider": str(event.get("provider") or "").strip(),
        "status": str(event.get("status") or "completed").strip() or "completed",
        "duration_ms": event.get("duration_ms"),
        "error": str(event.get("error") or "").strip(),
        "result_preview": str(event.get("result_preview") or "").strip(),
    }
    arguments = event.get("arguments")
    if isinstance(arguments, dict):
        part["args"] = arguments
    diagnostics = event.get("diagnostics")
    if isinstance(diagnostics, list):
        part["diagnostics"] = [str(item) for item in diagnostics]

    return {
        "id": f"tool-{call_id}",
        "role": "tool",
        "parts": [part],
        "created_at": now_text(),
    }
