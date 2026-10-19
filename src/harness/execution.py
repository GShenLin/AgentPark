"""Serialize a native conversation and project its live output into the node."""
from __future__ import annotations

from contextlib import contextmanager
import threading
from pathlib import Path
from typing import Iterator, Protocol

from nodes.agent_provider_runtime import stream_callback
from src.runtime_cancellation import raise_if_cancel_requested
from src.tool.tool_stats_store import ToolCallStatsRecorder
from .events import HarnessEvents
from .contracts import HarnessContext

_LOCK = threading.Lock()
_SESSIONS: dict[str, threading.Lock] = {}


class ExecutionRequest(Protocol):
    @property
    def state_dir(self) -> Path: ...

    @property
    def cancel_source(self) -> object: ...


@contextmanager
def execution_session(harness_id: str, provider_id: str, request: ExecutionRequest,
                      context: HarnessContext) -> Iterator[HarnessEvents]:
    with _LOCK:
        lock = _SESSIONS.setdefault(str(request.state_dir), threading.Lock())
    while not lock.acquire(timeout=0.1):
        raise_if_cancel_requested(request.cancel_source)
    try:
        raise_if_cancel_requested(request.cancel_source)
        request.state_dir.mkdir(parents=True, exist_ok=True)
        callback = stream_callback(context.values)
        stats = ToolCallStatsRecorder(provider_id=provider_id,
            graph_id=str(context.values.get("graph_id") or "default"),
            node_id=str(context.values.get("node_instance_id") or harness_id))

        def emit(event: dict) -> None:
            if event["type"] in {"tool_call_start", "tool_call_end"}:
                stats.handle(event)
            if callback:
                callback(event)

        yield HarnessEvents(harness_id, provider_id, emit)
    finally:
        lock.release()
