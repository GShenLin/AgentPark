from __future__ import annotations

from dataclasses import dataclass
from typing import Any


NODE_MESSAGE_DELTA = "node_message_delta"
NODE_MESSAGE_DONE = "node_message_done"
NODE_MESSAGE_EVENT_TYPES = {NODE_MESSAGE_DELTA, NODE_MESSAGE_DONE}


@dataclass(frozen=True)
class NodeMessageEvent:
    event_type: str
    text: str
    delta: str | None = None
    force: bool = False

    def to_payload(self) -> dict[str, Any]:
        if self.event_type not in NODE_MESSAGE_EVENT_TYPES:
            raise ValueError(f"unsupported node message event type: {self.event_type}")
        payload: dict[str, Any] = {
            "type": self.event_type,
            "text": self.text,
        }
        if self.event_type == NODE_MESSAGE_DELTA:
            payload["delta"] = "" if self.delta is None else self.delta
            if self.force:
                payload["force"] = True
        return payload


def build_node_message_delta(delta: object, text: object, *, force: bool = False) -> dict[str, Any]:
    return NodeMessageEvent(
        event_type=NODE_MESSAGE_DELTA,
        delta="" if delta is None else str(delta),
        text="" if text is None else str(text),
        force=force,
    ).to_payload()


def build_node_message_done(text: object) -> dict[str, Any]:
    return NodeMessageEvent(
        event_type=NODE_MESSAGE_DONE,
        text="" if text is None else str(text),
    ).to_payload()


def normalize_node_message_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("node message event must be an object")
    event_type = str(event.get("type") or "").strip().lower()
    if event_type not in NODE_MESSAGE_EVENT_TYPES:
        raise ValueError(f"unsupported node message event type: {event_type or '<empty>'}")
    text = str(event.get("text") or "")
    if event_type == NODE_MESSAGE_DELTA:
        return build_node_message_delta(
            event.get("delta"),
            text,
            force=bool(event.get("force")),
        )
    return build_node_message_done(text)
