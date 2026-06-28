from __future__ import annotations

import threading
import time
from typing import Any


class GraphEventStreamStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._versions: dict[str, int] = {}
        self._events: dict[str, dict[str, Any]] = {}

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
            payload["version"] = version
            self._events[safe_graph_id] = payload
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
            event = self._events.get(safe_graph_id)
            if isinstance(event, dict):
                return dict(event)
            return {"graph_id": safe_graph_id, "version": version}


__all__ = ["GraphEventStreamStore"]
