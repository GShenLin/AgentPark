"""Explicit recovery contracts for streams that already dispatched local tools."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.providers.responses_stream_events import ResponsesStreamEvent


@runtime_checkable
class ResponsesToolExecutionObserver(Protocol):
    def __call__(self, event: ResponsesStreamEvent) -> None: ...

    def has_started_tools(self) -> bool: ...

    def begin_attempt(self) -> None: ...


class ResponsesToolsInterrupted(RuntimeError):
    """A failed response, never a successful/synthetic provider response."""

    def __init__(self, error: Exception, *, retryable: bool) -> None:
        self.error = error
        self.retryable = retryable
        super().__init__(f"Response stream failed after tools were dispatched; original request replay blocked: {error}")


def tools_were_started(handler: object) -> bool:
    return isinstance(handler, ResponsesToolExecutionObserver) and handler.has_started_tools()
