from __future__ import annotations

import os
import threading

from src.runtime_cancellation import CancellationSignal


class ToolCallCancellationRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[tuple[str, str], CancellationSignal] = {}

    @staticmethod
    def _key(config_path: str, call_id: str) -> tuple[str, str]:
        path = os.path.normcase(os.path.abspath(str(config_path or "")))
        return path, str(call_id or "").strip()

    def begin(self, config_path: str, call_id: str) -> CancellationSignal:
        key = self._key(config_path, call_id)
        if not key[0] or not key[1]:
            raise ValueError("tool call cancellation requires config_path and call_id")
        event = CancellationSignal()
        with self._lock:
            if key in self._events:
                raise RuntimeError(f"tool call is already active: {key[1]}")
            self._events[key] = event
        return event

    def end(self, config_path: str, call_id: str, event: CancellationSignal) -> None:
        key = self._key(config_path, call_id)
        if not key[0] or not key[1]:
            return
        with self._lock:
            if self._events.get(key) is event:
                self._events.pop(key, None)

    def request(self, config_path: str, call_id: str) -> bool:
        key = self._key(config_path, call_id)
        if not key[0] or not key[1]:
            return False
        with self._lock:
            event = self._events.get(key)
        if event is None:
            return False
        event.set()
        return True

    def is_active(self, config_path: str, call_id: str) -> bool:
        key = self._key(config_path, call_id)
        if not key[0] or not key[1]:
            return False
        with self._lock:
            return key in self._events
