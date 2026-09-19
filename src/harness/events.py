"""Common live projection; native protocol parsing belongs to each adapter."""
from __future__ import annotations

import json
import time

from src.node_stream_protocol import build_node_message_delta, build_node_message_done, build_node_thinking_delta
from .contracts import EventHandler, HarnessResult


class HarnessEvents:
    def __init__(self, harness_id: str, provider_id: str, callback: EventHandler | None):
        self.harness_id = harness_id
        self.provider_id = provider_id
        self.callback = callback
        self.text = ""
        self.thinking = ""
        self.tools: dict[str, dict] = {}
        self.started: dict[str, float] = {}

    def emit(self, event: dict) -> None:
        if self.callback:
            self.callback(event)

    def text_delta(self, delta: str) -> None:
        self.text += delta
        self.emit(build_node_message_delta(delta, self.text))

    def thinking_delta(self, delta: str) -> None:
        self.thinking += delta
        self.emit(build_node_thinking_delta(delta, self.thinking, provider=self.provider_id))

    def tool(self, *, call_id: str, name: str, phase: str, value: object, error: bool = False) -> None:
        if not call_id:
            raise ValueError("Harness tool event requires a call id.")
        if phase == "running":
            self.started[call_id] = time.monotonic()
            event = {"type": "tool_call_start", "provider": self.harness_id, "call_id": call_id,
                     "name": name, "status": "running", "arguments": value}
        else:
            if call_id not in self.started:
                raise ValueError(f"Harness tool result has no matching call: {call_id}")
            previous = self.tools[call_id]
            preview = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            event = {**previous, "type": "tool_call_end", "status": "failed" if error else "completed",
                     "duration_ms": round((time.monotonic() - self.started.pop(call_id)) * 1000),
                     "result_preview": preview[:4000], "result_chars": len(preview),
                     "result_preview_truncated": len(preview) > 4000}
            if error:
                event["error"] = preview[:4000]
        self.tools[call_id] = event
        self.emit(event)

    def done(self, text: str) -> HarnessResult:
        if not isinstance(text, str):
            raise ValueError("Harness final text must be a string.")
        metadata = {"response_metadata": {"harness_id": self.harness_id,
                                           "runtime_tool_calls": list(self.tools.values())}}
        self.emit(build_node_message_done(text, **metadata))
        return HarnessResult(text, metadata)
