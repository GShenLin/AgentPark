from __future__ import annotations

from typing import Any


TOOL_ERROR_LINE_WIDTH = 120


def render_tool_event_lines(payload: dict[str, Any]) -> list[str]:
    event_type = str(payload.get("type") or "").strip()
    name = str(payload.get("name") or "tool").strip() or "tool"
    status = _tool_status(payload, event_type)
    duration = _duration_suffix(payload.get("duration_ms"))
    lines = [f"tool {name}: {status}{duration}"]

    error = str(payload.get("error") or "").strip()
    if event_type == "tool_call_end" and error:
        lines.extend(f"  error: {line}" for line in _error_display_lines(error))
    return lines


def _tool_status(payload: dict[str, Any], event_type: str) -> str:
    status = str(payload.get("status") or "").strip()
    if status:
        return status
    if event_type == "tool_call_start":
        return "running"
    return "finished"


def _duration_suffix(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    try:
        duration_ms = max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return ""
    return f" ({duration_ms} ms)"


def _error_display_lines(text: str) -> list[str]:
    wrapped: list[str] = []
    for raw_line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        if not line:
            wrapped.append("")
            continue
        wrapped.extend(_wrap_line(line, TOOL_ERROR_LINE_WIDTH))
    return wrapped or [""]


def _wrap_line(line: str, width: int) -> list[str]:
    if width <= 0 or len(line) <= width:
        return [line]
    return [line[index : index + width] for index in range(0, len(line), width)]
