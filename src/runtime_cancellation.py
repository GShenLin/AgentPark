from __future__ import annotations

import time
from typing import Any


class CancellationRequested(RuntimeError):
    """Raised when node execution is actively cancelled by the runtime."""


def is_cancel_requested(cancel_source: Any) -> bool:
    if cancel_source is None:
        return False
    if callable(cancel_source):
        try:
            return bool(cancel_source())
        except CancellationRequested:
            return True
        except Exception:
            return False
    is_set = getattr(cancel_source, "is_set", None)
    if callable(is_set):
        try:
            return bool(is_set())
        except Exception:
            return False
    return False


def raise_if_cancel_requested(cancel_source: Any) -> None:
    if is_cancel_requested(cancel_source):
        raise CancellationRequested("Operation cancelled.")


def cancel_source_from_agent(agent: object | None) -> Any:
    if agent is None:
        return None
    for name in ("cancel_event", "cancellation_event", "cancel_check"):
        value = getattr(agent, name, None)
        if value is not None:
            return value
    return None


def sleep_with_cancel(seconds: float, cancel_source: Any, *, interval: float = 0.05) -> None:
    remaining = max(0.0, float(seconds or 0))
    step = max(0.01, float(interval or 0.05))
    deadline = time.monotonic() + remaining
    while True:
        raise_if_cancel_requested(cancel_source)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(step, remaining))
