from __future__ import annotations

from typing import Any


NODE_EVENT_SEQ_FIELD = "node_event_seq"


def bump_node_event_seq(payload: dict[str, Any]) -> int:
    current = payload.get(NODE_EVENT_SEQ_FIELD)
    if isinstance(current, bool):
        current_seq = 0
    else:
        try:
            current_seq = int(current or 0)
        except (TypeError, ValueError):
            current_seq = 0
    next_seq = max(0, current_seq) + 1
    payload[NODE_EVENT_SEQ_FIELD] = next_seq
    return next_seq


def read_node_event_seq(payload: dict[str, Any]) -> int:
    value = payload.get(NODE_EVENT_SEQ_FIELD)
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


__all__ = ["NODE_EVENT_SEQ_FIELD", "bump_node_event_seq", "read_node_event_seq"]
