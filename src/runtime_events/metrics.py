from __future__ import annotations

import threading
from collections import Counter
from typing import Any


class RuntimeEventMetrics:
    def __init__(self) -> None:
        self._counter: Counter[str] = Counter()
        self._lock = threading.Lock()

    def inc(self, name: str, **labels: object) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counter[key] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._counter)

    @staticmethod
    def _key(name: str, labels: dict[str, object]) -> str:
        if not labels:
            return str(name)
        suffix = ",".join(f"{key}={labels[key]}" for key in sorted(labels))
        return f"{name}|{suffix}"
