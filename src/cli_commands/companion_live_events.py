from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from src.node_stream_protocol import NODE_MESSAGE_DELTA, NODE_MESSAGE_DONE, NODE_THINKING_DELTA


LiveActionKind = Literal["delta", "close", "activity", "tool", "server_tool"]


@dataclass(frozen=True)
class CompanionLiveAction:
    kind: LiveActionKind
    channel: str = ""
    text: str = ""
    event: dict[str, Any] | None = None


class CompanionLiveEventReducer:
    """Reduce the Agent/Web live-event protocol into presentation-neutral actions."""

    def __init__(self) -> None:
        self.answer_text = ""
        self.thinking_text = ""

    def consume(self, payload: object) -> list[CompanionLiveAction]:
        if not isinstance(payload, dict):
            return []
        event = dict(payload)
        event_type = str(event.get("type") or "").strip().lower()
        if event_type == NODE_MESSAGE_DELTA:
            delta, self.answer_text = _advance_text(self.answer_text, event)
            return [CompanionLiveAction("delta", channel="assistant", text=delta)] if delta else []
        if event_type == NODE_THINKING_DELTA:
            delta, self.thinking_text = _advance_text(self.thinking_text, event)
            return [CompanionLiveAction("delta", channel="thinking", text=delta)] if delta else []
        if event_type == NODE_MESSAGE_DONE:
            actions: list[CompanionLiveAction] = []
            final_text = str(event.get("text") or "")
            if final_text:
                delta, self.answer_text = _advance_text(self.answer_text, {"text": final_text, "delta": ""})
                if delta:
                    actions.append(CompanionLiveAction("delta", channel="assistant", text=delta))
            actions.append(CompanionLiveAction("close"))
            return actions
        if event_type in {"tool_call_start", "tool_call_end"}:
            return [CompanionLiveAction("tool", event=event)]
        if event_type == "server_tool_activity":
            return [CompanionLiveAction("server_tool", event=event)]
        if event_type == "runtime_notice":
            activity = format_live_activity(event)
            return [CompanionLiveAction("activity", text=activity, event=event)] if activity else []
        return []


def format_live_activity(event: dict[str, Any]) -> str:
    if str(event.get("type") or "").strip() != "runtime_notice":
        return ""
    if str(event.get("stage") or "").strip() != "openai_chat_native_web_search":
        return ""
    payload = _parse_object(event.get("message"))
    if not payload or str(payload.get("event") or "") != "native_web_search":
        return "Web search activity"
    preview = _parse_object(payload.get("preview")) or {}
    query = _find_string_field(preview, ("query", "keyword", "keywords", "search_query"))
    status = _find_string_field(preview, ("status", "state"))
    suffix = f" ({status})" if status else ""
    return f"Web search: {query}{suffix}" if query else f"Web search activity{suffix}"


def _advance_text(current: str, event: dict[str, Any]) -> tuple[str, str]:
    delta = str(event.get("delta") or "")
    cumulative = str(event.get("text") or "")
    if cumulative.startswith(current):
        suffix = cumulative[len(current) :]
        return suffix, cumulative
    if delta:
        return delta, cumulative or current + delta
    if not current and cumulative:
        return cumulative, cumulative
    return "", cumulative or current


def _parse_object(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return dict(parsed) if isinstance(parsed, dict) else None


def _find_string_field(value: object, keys: tuple[str, ...], depth: int = 0) -> str:
    if depth > 4 or value is None:
        return ""
    if isinstance(value, list):
        for item in value:
            found = _find_string_field(item, keys, depth + 1)
            if found:
                return found
        return ""
    if not isinstance(value, dict):
        return ""
    for key in keys:
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        if isinstance(raw, (int, float, bool)):
            return str(raw)
    for raw in value.values():
        found = _find_string_field(raw, keys, depth + 1)
        if found:
            return found
    return ""


__all__ = ["CompanionLiveAction", "CompanionLiveEventReducer", "format_live_activity"]
