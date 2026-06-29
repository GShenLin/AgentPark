from __future__ import annotations

import os
import threading
import time


class NodeCancellationRegistry:
    def __init__(self) -> None:
        self._condition = threading.Condition(threading.Lock())
        self._events_by_path: dict[str, set[threading.Event]] = {}

    @staticmethod
    def _key(config_path: str) -> str:
        return os.path.normcase(os.path.abspath(str(config_path or "")))

    def begin(self, config_path: str) -> threading.Event:
        event = threading.Event()
        key = self._key(config_path)
        if not key:
            return event
        with self._condition:
            events = self._events_by_path.get(key)
            if events is None:
                events = set()
                self._events_by_path[key] = events
            events.add(event)
        return event

    def end(self, config_path: str, event: threading.Event) -> None:
        key = self._key(config_path)
        if not key:
            return
        with self._condition:
            events = self._events_by_path.get(key)
            if events is None:
                return
            events.discard(event)
            if not events:
                self._events_by_path.pop(key, None)
            self._condition.notify_all()

    def request(self, config_path: str) -> int:
        key = self._key(config_path)
        if not key:
            return 0
        with self._condition:
            events = list(self._events_by_path.get(key) or ())
        for event in events:
            event.set()
        return len(events)

    def active_count(self, config_path: str) -> int:
        key = self._key(config_path)
        if not key:
            return 0
        with self._condition:
            return len(self._events_by_path.get(key) or ())

    def wait_until_idle(self, config_path: str, timeout_seconds: float) -> bool:
        key = self._key(config_path)
        if not key:
            return True
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        with self._condition:
            while self._events_by_path.get(key):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True
