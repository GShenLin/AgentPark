from __future__ import annotations

import uuid
from typing import Any

from src.message_protocol import build_text_envelope
from src.web_backend.node_memory_store import append_node_memory_entry
from src.web_backend.state_store import (
    _append_node_pending,
    _set_node_config_inflight,
    _transition_node_config_to_idle,
    _update_node_config_state,
)


class CompanionPromptInputBridge:
    """Connect prompt input to the normal Agent-node mid-turn input contract."""

    def __init__(self, target: Any) -> None:
        self.target = target

    def begin_turn(self, text: str) -> None:
        item = self._build_emit_item(text)
        _update_node_config_state(self.target.config_path, "working")
        _set_node_config_inflight(self.target.config_path, item)

    def submit_mid_turn(self, text: str) -> None:
        item = self._build_emit_item(text)
        _append_node_pending(self.target.config_path, item)
        append_node_memory_entry(
            self.target.memory_path,
            self.target.messages_path,
            "user",
            item["payload"],
        )

    def finish_turn(self) -> None:
        _set_node_config_inflight(self.target.config_path, None)
        _transition_node_config_to_idle(self.target.config_path)

    def _build_emit_item(self, text: str) -> dict[str, Any]:
        trace_id = uuid.uuid4().hex
        message = build_text_envelope(text, role="user")
        message["trace_id"] = trace_id
        return {
            "payload": message,
            "depth": 0,
            "visited": [],
            "trace_id": trace_id,
            "request_id": trace_id,
            "from": self.target.node_id,
            "source": "emit",
        }


__all__ = ["CompanionPromptInputBridge"]
