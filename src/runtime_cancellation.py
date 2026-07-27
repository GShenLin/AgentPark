from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable


class CancellationRequested(RuntimeError):
    """Raised when node execution is actively cancelled by the runtime."""


class CancellationSignal:
    """Thread-safe cancellation source with explicit cancellation callbacks."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_callback_id = 0

    def is_set(self) -> bool:
        return self._event.is_set()

    def set(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            callbacks = list(self._callbacks.values())
            self._callbacks.clear()
        errors: list[Exception] = []
        for callback in callbacks:
            try:
                callback()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]

    def register(self, callback: Callable[[], None]) -> Callable[[], None]:
        if not callable(callback):
            raise TypeError("cancellation callback must be callable")
        with self._lock:
            if self._event.is_set():
                invoke_now = True
                callback_id = None
            else:
                invoke_now = False
                callback_id = self._next_callback_id
                self._next_callback_id += 1
                self._callbacks[callback_id] = callback
        if invoke_now:
            callback()

        def unregister() -> None:
            if callback_id is None:
                return
            with self._lock:
                self._callbacks.pop(callback_id, None)

        return unregister


class CombinedCancellationSource:
    def __init__(self, sources: tuple[Any, ...]) -> None:
        self.sources = sources

    def is_set(self) -> bool:
        return any(is_cancel_requested(source) for source in self.sources)

    def register(self, callback: Callable[[], None]) -> Callable[[], None]:
        callback_lock = threading.Lock()
        callback_invoked = False

        def invoke_once() -> None:
            nonlocal callback_invoked
            with callback_lock:
                if callback_invoked:
                    return
                callback_invoked = True
            callback()

        unregister_callbacks = [
            register_cancel_callback(source, invoke_once)
            for source in self.sources
        ]

        def unregister() -> None:
            for unregister_callback in unregister_callbacks:
                unregister_callback()

        return unregister


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
    return CombinedCancellationSource(active)


def register_cancel_callback(
    cancel_source: Any,
    callback: Callable[[], None],
) -> Callable[[], None]:
    if cancel_source is None:
        return lambda: None
    register = getattr(cancel_source, "register", None)
    if not callable(register):
        return lambda: None
    unregister = register(callback)
    return unregister if callable(unregister) else lambda: None


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
