from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any


class GraphEventStreamStore:
    def __init__(self, *, history_limit: int = 256) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._versions: dict[str, int] = {}
        self._events: dict[str, dict[str, Any]] = {}
        self._history_limit = max(1, int(history_limit))
        self._history: dict[str, deque[dict[str, Any]]] = {}
        self._global_version = 0
        self._global_history: deque[dict[str, Any]] = deque(maxlen=self._history_limit)

    @staticmethod
    def _graph_id(value: object) -> str:
        return str(value or "default").strip() or "default"

    def publish(self, graph_id: str, event: dict[str, Any]) -> None:
        safe_graph_id = self._graph_id(graph_id)
        if not isinstance(event, dict):
            raise TypeError("graph event must be an object")
        with self._condition:
            version = int(self._versions.get(safe_graph_id) or 0) + 1
            self._versions[safe_graph_id] = version
            payload = dict(event)
            payload["graph_id"] = safe_graph_id
            payload["version"] = version
            self._events[safe_graph_id] = payload
            history = self._history.setdefault(safe_graph_id, deque(maxlen=self._history_limit))
            history.append(payload)
            self._global_version += 1
            global_payload = dict(payload)
            global_payload["global_version"] = self._global_version
            self._global_history.append(global_payload)
            self._condition.notify_all()

    def get(self, graph_id: str) -> dict[str, Any]:
        safe_graph_id = self._graph_id(graph_id)
        with self._lock:
            version = int(self._versions.get(safe_graph_id) or 0)
            event = self._events.get(safe_graph_id)
            if isinstance(event, dict):
                return dict(event)
            return {"graph_id": safe_graph_id, "version": version}

    def wait_for_change(self, graph_id: str, last_version: int, timeout: float = 15.0) -> dict[str, Any]:
        safe_graph_id = self._graph_id(graph_id)
        deadline = time.monotonic() + max(0.1, float(timeout or 0.1))
        with self._condition:
            while int(self._versions.get(safe_graph_id) or 0) <= int(last_version or 0):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)
            version = int(self._versions.get(safe_graph_id) or 0)
            history = self._history.get(safe_graph_id)
            if history:
                for event in history:
                    if int(event.get("version") or 0) > int(last_version or 0):
                        return dict(event)
            event = self._events.get(safe_graph_id)
            if isinstance(event, dict):
                return dict(event)
            return {"graph_id": safe_graph_id, "version": version}

    def get_global_version(self) -> int:
        with self._lock:
            return self._global_version

    def wait_for_global_change(self, last_version: int, timeout: float = 15.0) -> dict[str, Any] | None:
        deadline = time.monotonic() + max(0.1, float(timeout or 0.1))
        with self._condition:
            while self._global_version <= int(last_version or 0):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(timeout=remaining)
            if self._global_history:
                oldest_version = int(self._global_history[0].get("global_version") or 0)
                expected_version = int(last_version or 0) + 1
                if oldest_version > expected_version:
                    return {
                        "event": "stream_gap",
                        "from_global_version": expected_version,
                        "to_global_version": oldest_version - 1,
                        "global_version": oldest_version - 1,
                    }
            for event in self._global_history:
                if int(event.get("global_version") or 0) > int(last_version or 0):
                    return dict(event)
            return None


__all__ = ["GraphEventStreamStore"]
