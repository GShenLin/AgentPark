from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from typing import Any


class RuntimeEventDiagnostics:
    def __init__(self, limit: int = 100) -> None:
        self._items: deque[dict[str, Any]] = deque(maxlen=max(1, int(limit)))
        self._lock = threading.Lock()

    def record(
        self,
        *,
        kind: str,
        message: str,
        error: BaseException | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "ts": datetime.now().astimezone().isoformat(),
            "kind": str(kind or "runtime_event_error"),
            "message": str(message or ""),
        }
        if error is not None:
            payload["error_type"] = type(error).__name__
            payload["error"] = str(error)
        if details:
            payload["details"] = _bounded_details(details)
        with self._lock:
            self._items.append(payload)

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._items)


def _bounded_details(details: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in list(details.items())[:32]:
        output[str(key)] = _bounded_value(value)
    return output


def _bounded_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:1000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _bounded_value(item) for key, item in list(value.items())[:16]}
    if isinstance(value, (list, tuple)):
        return [_bounded_value(item) for item in list(value)[:16]]
    return str(value)[:1000]
