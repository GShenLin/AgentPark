"""Owned resident JSONL transport; protocol admission and completion belong to adapters."""
from __future__ import annotations

from collections import deque
import json
import os
import queue
import subprocess
import threading
import time

from src.runtime_cancellation import raise_if_cancel_requested
from .process import stop_process


class JsonlProcess:
    def __init__(self, argv, *, cwd, env, timeout, cancel_source=None):
        self.job = None
        self.closed = threading.Event()
        self.disposed = False
        self.inbox = queue.Queue(maxsize=256)
        self.errors = deque(maxlen=100)
        self.process = None
        if os.name == "nt":
            from .windows_job import WindowsJob
            self.job = WindowsJob()
        try:
            self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt")
            if self.job:
                self.job.assign(int(self.process._handle))
        except BaseException:
            if self.process:
                stop_process(self.process)
            if self.job:
                self.job.close()
            raise
        self.reset(timeout, cancel_source)
        self.workers = [threading.Thread(target=self._read, daemon=True),
                        threading.Thread(target=self._read_errors, daemon=True)]
        for worker in self.workers:
            worker.start()

    def reset(self, timeout, cancel_source):
        self.deadline = time.monotonic() + timeout
        self.cancel_source = cancel_source

    def is_alive(self):
        return not self.closed.is_set() and self.process.poll() is None

    def _put(self, value):
        while not self.closed.is_set():
            try:
                self.inbox.put(value, timeout=0.1)
                return
            except queue.Full:
                continue

    def _read(self):
        try:
            while line := self.process.stdout.readline(16 * 1024 * 1024 + 1):
                if len(line) > 16 * 1024 * 1024:
                    raise ValueError("Harness JSONL frame exceeds 16 MiB.")
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("Harness JSONL frame must be an object.")
                self._put(value)
        except Exception as exc:
            self._put(exc)
        finally:
            self._put(None)

    def _read_errors(self):
        try:
            while line := self.process.stderr.readline(8192):
                self.errors.append(line)
        except Exception as exc:
            self._put(exc)

    def send(self, value):
        raise_if_cancel_requested(self.cancel_source)
        self.process.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def receive(self):
        while True:
            raise_if_cancel_requested(self.cancel_source)
            if time.monotonic() >= self.deadline:
                raise TimeoutError("Harness response timed out. " + "".join(self.errors)[-4000:])
            try:
                value = self.inbox.get(timeout=0.1)
            except queue.Empty:
                if self.closed.is_set():
                    raise RuntimeError("Harness process was closed.")
                continue
            if value is None:
                raise RuntimeError("Harness exited before completing the request. " + "".join(self.errors)[-12000:])
            if isinstance(value, Exception):
                raise value
            return value

    def close(self):
        if self.disposed:
            return
        self.closed.set()
        try:
            self.process.stdin.close()
        finally:
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                stop_process(self.process)
            finally:
                if self.job:
                    self.job.close()
        for worker in self.workers:
            worker.join(timeout=2)
            if worker.is_alive():
                raise RuntimeError("Harness pipe reader did not stop after closing its process tree.")
        self.process.stdout.close()
        self.process.stderr.close()
        self.disposed = True
