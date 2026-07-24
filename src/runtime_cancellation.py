from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any


class CancellationRequested(RuntimeError):
    """Raised when node execution is actively cancelled by the runtime."""


_TOOL_CALL_CANCEL_SOURCE: ContextVar[Any] = ContextVar(
    "agentpark_tool_call_cancel_source",
    default=None,
)


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
    sources = []
    current_tool_source = _TOOL_CALL_CANCEL_SOURCE.get()
    if current_tool_source is not None:
        sources.append(current_tool_source)
    if agent is not None:
        for name in ("cancel_event", "cancel_check"):
            value = getattr(agent, name, None)
            if value is not None:
                sources.append(value)
                break
    return combine_cancel_sources(*sources)


def current_tool_call_cancel_source() -> Any:
    return _TOOL_CALL_CANCEL_SOURCE.get()


def combine_cancel_sources(*sources: Any) -> Any:
    active = tuple(source for source in sources if source is not None)
    if not active:
        return None
    if len(active) == 1:
        return active[0]
    return lambda: any(is_cancel_requested(source) for source in active)


@contextmanager
def tool_call_cancellation_scope(cancel_source: Any):
    token = _TOOL_CALL_CANCEL_SOURCE.set(cancel_source)
    try:
        yield
    finally:
        _TOOL_CALL_CANCEL_SOURCE.reset(token)


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
