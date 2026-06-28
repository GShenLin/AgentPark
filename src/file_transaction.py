from __future__ import annotations

import os
import tempfile
import threading
import time
from contextlib import contextmanager
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, TypeVar


T = TypeVar("T")
_FILE_LOCK_LOCAL = threading.local()


@dataclass
class _QueuedTask:
    func: Callable[[], object]
    done: threading.Event = field(default_factory=threading.Event)
    result: object = None
    error: BaseException | None = None


@dataclass
class _QueueState:
    tasks: deque[_QueuedTask] = field(default_factory=deque)
    running: bool = False


class KeyedTransactionQueue:
    def __init__(self) -> None:
        self._states: dict[str, _QueueState] = {}
        self._guard = threading.Lock()
        self._local = threading.local()

    def run(self, key: str, func: Callable[[], T]) -> T:
        safe_key = canonical_path_key(key)
        if not safe_key:
            return func()
        if self._is_active(safe_key):
            return func()

        task = _QueuedTask(func=func)
        should_drain = False
        with self._guard:
            state = self._states.get(safe_key)
            if state is None:
                state = _QueueState()
                self._states[safe_key] = state
            state.tasks.append(task)
            if not state.running:
                state.running = True
                should_drain = True

        if should_drain:
            self._drain(safe_key, state)
        else:
            task.done.wait()

        if task.error is not None:
            raise task.error
        return task.result  # type: ignore[return-value]

    def wait_empty(self, key: str) -> None:
        self.run(key, lambda: None)

    def _drain(self, key: str, state: _QueueState) -> None:
        active = self._active_keys()
        active.append(key)
        try:
            while True:
                with self._guard:
                    if not state.tasks:
                        state.running = False
                        if not state.tasks:
                            self._states.pop(key, None)
                        return
                    task = state.tasks.popleft()
                try:
                    task.result = task.func()
                except BaseException as exc:
                    task.error = exc
                finally:
                    task.done.set()
        finally:
            active.pop()

    def _active_keys(self) -> list[str]:
        active = getattr(self._local, "active_keys", None)
        if not isinstance(active, list):
            active = []
            self._local.active_keys = active
        return active

    def _is_active(self, key: str) -> bool:
        return key in self._active_keys()


def canonical_path_key(path: str) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    return os.path.normcase(os.path.abspath(text))


def atomic_write_text(path: str, text: str, *, encoding: str = "utf-8") -> None:
    if not path:
        raise ValueError("path is empty")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=parent or os.curdir)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as handle:
            handle.write(text)
        _replace_with_retry(tmp_path, path)
        tmp_path = ""
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def append_text(path: str, text: str, *, encoding: str = "utf-8") -> None:
    if not path:
        raise ValueError("path is empty")
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding=encoding) as handle:
        handle.write(text)


def touch_file(path: str, *, encoding: str = "utf-8") -> None:
    append_text(path, "", encoding=encoding)


def run_with_interprocess_lock(lock_path: str, func: Callable[[], T]) -> T:
    safe_key = canonical_path_key(lock_path)
    if not safe_key:
        return func()
    active = _active_file_lock_keys()
    if safe_key in active:
        return func()
    active.append(safe_key)
    try:
        with _interprocess_file_lock(lock_path):
            return func()
    finally:
        active.pop()


def replace_path(source: str, target: str) -> None:
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    _replace_with_retry(source, target)


def _active_file_lock_keys() -> list[str]:
    active = getattr(_FILE_LOCK_LOCAL, "active_keys", None)
    if not isinstance(active, list):
        active = []
        _FILE_LOCK_LOCAL.active_keys = active
    return active


@contextmanager
def _interprocess_file_lock(lock_path: str):
    parent = os.path.dirname(lock_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(lock_path, "a+b") as handle:
        _lock_file_region(handle)
        try:
            yield
        finally:
            _unlock_file_region(handle)


def _lock_file_region(handle) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_file_region(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _replace_with_retry(source: str, target: str) -> None:
    delays = (0.01, 0.025, 0.05, 0.1)
    last_error: OSError | None = None
    for index, delay in enumerate((0.0, *delays)):
        if delay:
            time.sleep(delay)
        try:
            os.replace(source, target)
            return
        except PermissionError as exc:
            last_error = exc
        except OSError as exc:
            if not _is_windows_replace_retryable(exc):
                raise
            last_error = exc
        if index == len(delays):
            break
    if last_error is not None:
        raise last_error


def _is_windows_replace_retryable(error: OSError) -> bool:
    if os.name != "nt":
        return False
    winerror = getattr(error, "winerror", None)
    return winerror in {5, 32}
