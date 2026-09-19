"""Bounded, cancellable subprocess IO, with no shell command interpolation."""
from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable

from src.runtime_cancellation import raise_if_cancel_requested


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        result = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode and process.poll() is None:
            process.kill()
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=10)


def run_process(argv: list[str], *, cwd: str, env: dict[str, str] | None = None,
                stdin: str = "", timeout: float = 900, cancel_source: object = None,
                on_line: Callable[[str], None] | None = None,
                on_stderr_line: Callable[[str], None] | None = None) -> str:
    raise_if_cancel_requested(cancel_source)
    process = subprocess.Popen(
        argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="strict",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        start_new_session=os.name != "nt",
    )
    events: queue.Queue = queue.Queue(maxsize=256)
    errors: deque[str] = deque(maxlen=100)
    shutdown = threading.Event()

    def enqueue(item: object) -> None:
        while not shutdown.is_set():
            try:
                events.put(item, timeout=0.1)
                return
            except queue.Full:
                continue

    def read_stdout() -> None:
        try:
            while line := process.stdout.readline(16 * 1024 * 1024 + 1):
                if len(line) > 16 * 1024 * 1024:
                    raise ValueError("Harness output line exceeds 16 MiB.")
                enqueue(("stdout", line))
        except Exception as exc:
            enqueue(exc)
        finally:
            enqueue(("stdout", None))

    def read_stderr() -> None:
        try:
            line_limit = 16 * 1024 * 1024 if on_stderr_line else 8192
            while line := process.stderr.readline(line_limit + 1 if on_stderr_line else line_limit):
                if on_stderr_line and len(line) > line_limit:
                    raise ValueError("Harness stderr line exceeds its framing limit.")
                errors.append(line[-8192:])
                if on_stderr_line:
                    enqueue(("stderr", line))
        except Exception as exc:
            enqueue(exc)
        finally:
            enqueue(("stderr", None))

    def write_stdin() -> None:
        try:
            process.stdin.write(stdin)
            process.stdin.close()
        except Exception as exc:
            enqueue(exc)

    workers = [threading.Thread(target=target, daemon=True)
               for target in (read_stdout, read_stderr, write_stdin)]
    for worker in workers:
        worker.start()
    output: list[str] = []
    size = 0
    deadline = time.monotonic() + timeout
    finished_streams: set[str] = set()
    try:
        while len(finished_streams) < 2 or process.poll() is None:
            raise_if_cancel_requested(cancel_source)
            if time.monotonic() > deadline:
                raise TimeoutError(f"Harness process timed out after {timeout:g} seconds.")
            try:
                item = events.get(timeout=0.1)
            except queue.Empty:
                continue
            if isinstance(item, Exception):
                raise item
            stream, line = item
            if line is None:
                finished_streams.add(stream)
            elif stream == "stderr":
                on_stderr_line(line)
            elif on_line:
                on_line(line)
            else:
                size += len(line)
                if size > 16 * 1024 * 1024:
                    raise ValueError("Harness output exceeds 16 MiB.")
                output.append(line)
        if process.returncode:
            raise RuntimeError(f"Harness exited with code {process.returncode}: {''.join(errors)[-12000:]}")
        return "".join(output)
    finally:
        shutdown.set()
        stop_process(process)
        for worker in workers:
            worker.join(timeout=2)
        for pipe in (process.stdin, process.stdout, process.stderr):
            pipe.close()
