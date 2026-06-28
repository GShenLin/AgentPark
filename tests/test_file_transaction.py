import multiprocessing
import os
import time
from pathlib import Path

import pytest

import src.file_transaction as file_transaction
from src.file_transaction import atomic_write_text
from src.file_transaction import run_with_interprocess_lock


def _append_marker(path: str, text: str) -> None:
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text + "\n")


def _hold_interprocess_lock(lock_path: str, marker_path: str, ready_path: str) -> None:
    def body() -> None:
        _append_marker(marker_path, "holder-enter")
        Path(ready_path).write_text("ready", encoding="utf-8")
        time.sleep(0.4)
        _append_marker(marker_path, "holder-exit")

    run_with_interprocess_lock(lock_path, body)


def _wait_for_interprocess_lock(lock_path: str, marker_path: str) -> None:
    def body() -> None:
        _append_marker(marker_path, "waiter-enter")

    run_with_interprocess_lock(lock_path, body)


def test_atomic_write_cleanup_does_not_mask_replace_error(tmp_path, monkeypatch):
    target = tmp_path / "memory.md"

    def fail_replace(_source, _target):
        raise PermissionError("locked target")

    def fail_remove(_path):
        raise PermissionError("locked temp")

    monkeypatch.setattr(os, "replace", fail_replace)
    monkeypatch.setattr(os, "remove", fail_remove)
    monkeypatch.setattr(file_transaction.time, "sleep", lambda _seconds: None)

    with pytest.raises(PermissionError, match="locked target"):
        atomic_write_text(str(target), "hello")


def test_interprocess_file_lock_serializes_processes(tmp_path):
    lock_path = str(tmp_path / ".node-memory.lock")
    marker_path = str(tmp_path / "marker.txt")
    ready_path = tmp_path / "ready.txt"
    ctx = multiprocessing.get_context("spawn")

    holder = ctx.Process(target=_hold_interprocess_lock, args=(lock_path, marker_path, str(ready_path)))
    waiter = ctx.Process(target=_wait_for_interprocess_lock, args=(lock_path, marker_path))
    holder.start()
    deadline = time.monotonic() + 5
    while not ready_path.exists() and time.monotonic() < deadline:
        time.sleep(0.025)
    assert ready_path.exists()

    waiter.start()
    holder.join(10)
    waiter.join(10)

    assert holder.exitcode == 0
    assert waiter.exitcode == 0
    lines = Path(marker_path).read_text(encoding="utf-8").splitlines()
    assert lines == ["holder-enter", "holder-exit", "waiter-enter"]


def test_interprocess_file_lock_is_reentrant_in_same_thread(tmp_path):
    lock_path = str(tmp_path / ".node-memory.lock")

    result = run_with_interprocess_lock(lock_path, lambda: run_with_interprocess_lock(lock_path, lambda: "ok"))

    assert result == "ok"
