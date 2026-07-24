from __future__ import annotations

import threading
import time
from typing import Any

from .node_live_output import build_live_output_payload


DEFAULT_LIVE_PUBLISH_INTERVAL_SECONDS = 0.08
IMMEDIATE_LIVE_EVENT_TYPES = {
    "node_message_done",
    "node_error",
    "stdin_ready",
    "stdin_closed",
    "audio_stream_end",
}


def build_coalesced_live_payload(
    graph_id: str,
    node_id: str,
    previous: dict[str, Any] | None,
    current: dict[str, Any],
) -> dict[str, Any]:
    previous_version = int((previous or {}).get("version") or 0)
    current_version = int(current.get("version") or 0)
    previous_text = str((previous or {}).get("text") or "")
    current_text = str(current.get("text") or "")
    previous_thinking = str((previous or {}).get("thinking_text") or "")
    current_thinking = str(current.get("thinking_text") or "")
    same_trace = str((previous or {}).get("trace_id") or "") == str(current.get("trace_id") or "")
    can_send_delta = bool(previous) and same_trace and current_text.startswith(previous_text) and current_thinking.startswith(previous_thinking)
    if not can_send_delta:
        return build_live_output_payload(
            graph_id,
            node_id,
            current,
            snapshot=True,
            last_delivered_version=previous_version,
        )

    coalesced = dict(current)
    coalesced["live_delta"] = current_text[len(previous_text):]
    coalesced["thinking_delta"] = current_thinking[len(previous_thinking):]
    coalesced["snapshot_required"] = False
    payload = build_live_output_payload(
        graph_id,
        node_id,
        coalesced,
        last_delivered_version=max(0, current_version - 1),
    )
    payload["base_version"] = previous_version
    return payload


class NodeLiveEventPublisher:
    """Coalesce high-frequency node output into bounded-rate SSE frames."""

    def __init__(self, event_store, *, interval_seconds: float = DEFAULT_LIVE_PUBLISH_INTERVAL_SECONDS) -> None:
        self._event_store = event_store
        self._interval = max(0.01, float(interval_seconds))
        self._condition = threading.Condition()
        self._pending: dict[tuple[str, str], dict[str, Any]] = {}
        self._published: dict[tuple[str, str], dict[str, Any]] = {}
        self._published_at: dict[tuple[str, str], float] = {}
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="node-live-publisher", daemon=True)
        self._thread.start()

    def publish(self, graph_id: str, node_id: str, live: dict) -> None:
        key = (str(graph_id or "default").strip() or "default", str(node_id or "").strip())
        if not key[1] or not isinstance(live, dict):
            return
        current = dict(live)
        event_type = str(current.get("event_type") or "").strip().lower()
        with self._condition:
            if self._closed:
                return
            self._pending[key] = current
            first_frame = key not in self._published
            due = time.monotonic() >= self._published_at.get(key, 0.0) + self._interval
            if first_frame or event_type in IMMEDIATE_LIVE_EVENT_TYPES or due:
                self._pending.pop(key, None)
                self._emit_locked(key, current)
            else:
                self._condition.notify()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._pending.clear()
            self._condition.notify_all()
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._closed and not self._pending:
                    self._condition.wait()
                if self._closed:
                    return
                now = time.monotonic()
                due_at = min(
                    self._published_at.get(key, 0.0) + self._interval
                    for key in self._pending
                )
                if due_at > now:
                    self._condition.wait(timeout=due_at - now)
                    continue
                due_keys = [
                    key
                    for key in self._pending
                    if self._published_at.get(key, 0.0) + self._interval <= now
                ]
                for key in due_keys:
                    current = self._pending.pop(key)
                    self._emit_locked(key, current)

    def _emit_locked(self, key: tuple[str, str], current: dict[str, Any]) -> None:
        previous = self._published.get(key)
        if previous is not None and int(current.get("version") or 0) <= int(previous.get("version") or 0):
            return
        payload = build_coalesced_live_payload(key[0], key[1], previous, current)
        self._event_store.publish(
            key[0],
            {
                "event": "node_live",
                "node_id": key[1],
                "node_instance_id": key[1],
                "live": payload,
            },
        )
        self._published[key] = current
        self._published_at[key] = time.monotonic()


__all__ = [
    "DEFAULT_LIVE_PUBLISH_INTERVAL_SECONDS",
    "IMMEDIATE_LIVE_EVENT_TYPES",
    "NodeLiveEventPublisher",
    "build_coalesced_live_payload",
]
