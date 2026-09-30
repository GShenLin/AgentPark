"""Synchronous ACP JSON-RPC stdio client for one owned session at a time."""
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


class AcpClient:
    def __init__(self, argv: list[str], *, cwd: str, env: dict, timeout: float, cancel_source: object, on_update):
        self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                        start_new_session=os.name != "nt")
        self.deadline = time.monotonic() + timeout
        self.cancel_source = cancel_source
        self.on_update = on_update
        self.inbox: queue.Queue = queue.Queue(maxsize=256)
        self.errors: deque[str] = deque(maxlen=100)
        self.closed = threading.Event()
        self.sequence = 0
        self.workers = [threading.Thread(target=self._read, daemon=True),
                        threading.Thread(target=self._read_errors, daemon=True)]
        for worker in self.workers:
            worker.start()

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
                    raise ValueError("ACP frame exceeds 16 MiB.")
                value = json.loads(line)
                if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
                    raise ValueError("ACP stdout must contain JSON-RPC 2.0 objects.")
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

    def _write(self, value: dict):
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", **value}, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict) -> dict:
        raise_if_cancel_requested(self.cancel_source)
        self.sequence += 1
        request_id = self.sequence
        self._write({"id": request_id, "method": method, "params": params})
        while True:
            raise_if_cancel_requested(self.cancel_source)
            if time.monotonic() > self.deadline:
                raise TimeoutError(f"ACP request timed out: {method}. {''.join(self.errors)[-4000:]}")
            try:
                message = self.inbox.get(timeout=0.1)
            except queue.Empty:
                continue
            if message is None:
                raise RuntimeError(f"ACP closed during {method}: {''.join(self.errors)[-12000:]}")
            if isinstance(message, Exception):
                raise message
            if "method" in message:
                if message["method"] == "session/update" and "id" not in message:
                    params = message.get("params")
                    if not isinstance(params, dict):
                        raise ValueError("ACP session/update requires params.")
                    self.on_update(params)
                elif "id" in message:
                    if message["method"] == "session/request_permission":
                        self._write({"id": message["id"], "result": {"outcome": {"outcome": "cancelled"}}})
                        raise RuntimeError("ACP runtime requested interactive permission; this node supports unattended execution only.")
                    self._write({"id": message["id"], "error": {"code": -32601, "message": "Client method not supported"}})
                    raise RuntimeError(f"Unsupported ACP client request: {message['method']}")
                continue
            if message.get("id") != request_id:
                raise ValueError("Unexpected ACP response id.")
            if "error" in message:
                raise RuntimeError(f"ACP {method} failed: {message['error']}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise ValueError(f"ACP {method} result must be an object.")
            return result

    def close(self):
        self.closed.set()
        self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            stop_process(self.process)
        for worker in self.workers:
            worker.join(timeout=2)
        self.process.stdout.close()
        self.process.stderr.close()
