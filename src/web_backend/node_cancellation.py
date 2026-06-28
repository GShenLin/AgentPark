from __future__ import annotations

import os
import threading


class NodeCancellationRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events_by_path: dict[str, set[threading.Event]] = {}

    @staticmethod
    def _key(config_path: str) -> str:
        return os.path.normcase(os.path.abspath(str(config_path or "")))

    def begin(self, config_path: str) -> threading.Event:
        event = threading.Event()
        key = self._key(config_path)
        if not key:
            return event
        with self._lock:
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
        with self._lock:
            events = self._events_by_path.get(key)
            if events is None:
                return
            events.discard(event)
            if not events:
                self._events_by_path.pop(key, None)

    def request(self, config_path: str) -> int:
        key = self._key(config_path)
        if not key:
            return 0
        with self._lock:
            events = list(self._events_by_path.get(key) or ())
        for event in events:
            event.set()
        return len(events)
