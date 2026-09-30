"""Node-scoped coordination for background and foreground history compaction."""
from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable
from weakref import WeakValueDictionary

from src.runtime_cancellation import raise_if_cancel_requested

LOG = logging.getLogger(__name__)


@dataclass
class _NodeJob:
    execution: threading.Lock = field(default_factory=threading.Lock)
    pending: Callable[[], None] | None = None
    future: Future | None = None


class CompactionCoordinator:
    def __init__(self):
        self._guard = threading.Lock()
        self._nodes: WeakValueDictionary[str, _NodeJob] = WeakValueDictionary()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="conversation-compaction")

    def _node(self, path: str) -> _NodeJob:
        key = os.path.normcase(os.path.abspath(path))
        with self._guard:
            state = self._nodes.get(key)
            if state is None:
                state = _NodeJob()
                self._nodes[key] = state
            return state

    @contextmanager
    def exclusive(self, path: str, cancel_source=None):
        state = self._node(path)
        while True:
            raise_if_cancel_requested(cancel_source)
            if state.execution.acquire(timeout=0.1):
                break
        try:
            raise_if_cancel_requested(cancel_source)
            yield
        finally:
            state.execution.release()

    def schedule(self, path: str, operation: Callable[[], None]) -> Future:
        state = self._node(path)
        with self._guard:
            # Coalesce additional completed turns into a check of the latest boundary.
            state.pending = operation
            if state.future is None:
                state.future = self._pool.submit(self._drain, state, path)
            return state.future

    def _drain(self, state: _NodeJob, path: str):
        failure = None
        while True:
            with self._guard:
                operation, state.pending = state.pending, None
                if operation is None:
                    state.future = None
                    break
            try:
                operation()
                failure = None
            except Exception as exc:
                failure = exc
                LOG.exception("Background conversation compaction failed for %s", path)
        if failure is not None:
            raise failure

    def shutdown(self):
        self._pool.shutdown(wait=True)


coordinator = CompactionCoordinator()
