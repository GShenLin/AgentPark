"""Owned OpenClaw process and its public Gateway v4 WebSocket contract.

The process survives turns; sockets are turn-scoped. No CLI intermediary or
private OpenClaw module imports are involved in submitting a message.
"""
from __future__ import annotations

from collections import deque
import json
import os
import subprocess
import sys
import threading
import time
import uuid

from websockets.sync.client import connect

from src.runtime_cancellation import CancellationRequested, raise_if_cancel_requested
from .process import stop_process


class GatewayError(RuntimeError):
    def __init__(self, error: dict):
        self.error = error
        super().__init__(f"OpenClaw Gateway: {error}")


class OpenClawGateway:
    def __init__(self, argv: list[str], *, cwd: str, env: dict, port: int, token: str):
        self.url = f"ws://127.0.0.1:{port}"
        self.token = token
        self.diagnostics: deque[str] = deque(maxlen=100)
        self.job = None
        if os.name == "nt":
            from .windows_job import WindowsJob
            self.job = WindowsJob()
        self.process = None
        try:
            self.process = subprocess.Popen(
                [*argv, "gateway", "run"], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            if self.job:
                self.job.assign(int(self.process._handle))
        except BaseException:
            if self.process is not None:
                stop_process(self.process)
                self.process.stdout.close()
            if self.job:
                self.job.close()
            raise
        self.reader = threading.Thread(target=self._read_diagnostics, daemon=True)
        self.reader.start()

    def _read_diagnostics(self) -> None:
        while line := self.process.stdout.readline(8192):
            self.diagnostics.append(line)

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def _check(self, deadline: float, cancel_source) -> None:
        raise_if_cancel_requested(cancel_source)
        if not self.is_alive():
            raise RuntimeError(f"OpenClaw exited with code {self.process.returncode}: "
                               + "".join(self.diagnostics)[-12000:])
        if time.monotonic() >= deadline:
            raise TimeoutError("OpenClaw Gateway request timed out.")

    def _receive(self, ws, deadline, cancel_source) -> dict:
        while True:
            self._check(deadline, cancel_source)
            try:
                raw = ws.recv(timeout=min(0.1, max(0.001, deadline - time.monotonic())))
            except TimeoutError:
                continue
            frame = json.loads(raw)
            if not isinstance(frame, dict) or frame.get("type") not in {"res", "event"}:
                raise ValueError("Invalid OpenClaw Gateway frame.")
            return frame

    @staticmethod
    def _send(ws, method: str, params: dict) -> str:
        request_id = uuid.uuid4().hex
        ws.send(json.dumps({"type": "req", "id": request_id, "method": method, "params": params}))
        return request_id

    def _response(self, ws, request_id, deadline, cancel_source, on_event=None) -> dict:
        while True:
            frame = self._receive(ws, deadline, cancel_source)
            if frame["type"] == "event":
                if frame.get("event") == "agent" and on_event:
                    on_event(frame.get("payload"))
                elif frame.get("event") == "shutdown":
                    raise RuntimeError(f"OpenClaw is shutting down: {frame.get('payload')}")
                continue
            if frame.get("id") != request_id:
                raise ValueError("OpenClaw response does not match the active request.")
            if frame.get("ok") is False and isinstance(frame.get("error"), dict):
                raise GatewayError(frame["error"])
            if frame.get("ok") is not True or not isinstance(frame.get("payload"), dict):
                raise ValueError("Invalid OpenClaw response payload.")
            return frame["payload"]

    def _connect(self, deadline, cancel_source):
        while True:
            self._check(deadline, cancel_source)
            try:
                ws = connect(self.url, proxy=None, open_timeout=min(1, deadline - time.monotonic()),
                             close_timeout=1, max_size=32 * 1024 * 1024)
            except (ConnectionRefusedError, TimeoutError):
                time.sleep(0.1)
                continue
            try:
                challenge = self._receive(ws, deadline, cancel_source)
                if challenge.get("event") != "connect.challenge":
                    raise ValueError("OpenClaw Gateway did not send a connect challenge.")
                request_id = self._send(ws, "connect", {
                    "minProtocol": 4, "maxProtocol": 4,
                    "client": {"id": "gateway-client", "displayName": "AgentPark", "version": "1",
                               "platform": sys.platform, "mode": "backend"},
                    "role": "operator", "scopes": ["operator.read", "operator.write"],
                    "caps": ["tool-events"], "auth": {"token": self.token},
                })
                hello = self._response(ws, request_id, deadline, cancel_source)
                if hello.get("type") != "hello-ok" or hello.get("protocol") != 4:
                    raise ValueError("OpenClaw requires Gateway protocol version 4.")
                if "agent" not in hello.get("features", {}).get("methods", []):
                    raise ValueError("OpenClaw Gateway does not support agent requests.")
                return ws
            except GatewayError as exc:
                ws.close()
                error = exc.error
                delay = error.get("retryAfterMs")
                if (error.get("code") != "UNAVAILABLE" or error.get("retryable") is not True
                        or error.get("details", {}).get("reason") != "startup-sidecars"
                        or type(delay) is not int or not 0 < delay <= 10000):
                    raise
                until = min(deadline, time.monotonic() + delay / 1000)
                while time.monotonic() < until:
                    self._check(deadline, cancel_source)
                    time.sleep(min(0.1, max(0, until - time.monotonic())))
            except BaseException:
                ws.close()
                raise

    def _submit(self, ws, params, deadline, cancel_source, on_event):
        # The listener/hello can be ready while the selected agent's database
        # is still being inspected. This typed refusal is explicitly pre-admission.
        while True:
            self._check(deadline, cancel_source)
            request_id = self._send(ws, "agent", params)
            try:
                return request_id, self._response(ws, request_id, deadline, cancel_source, on_event)
            except (CancellationRequested, TimeoutError):
                # The request may have been accepted even if cancellation won
                # the race with reading its acknowledgement. OpenClaw uses the
                # idempotency key as the run ID for this exact abort case.
                self._abort(ws, request_id, {"runId": params["idempotencyKey"]}, params["sessionKey"])
                raise
            except GatewayError as exc:
                error = exc.error
                delay = error.get("retryAfterMs")
                if (error.get("code") != "UNAVAILABLE" or error.get("retryable") is not True
                        or error.get("details", {}).get("code") != "agent-database-inspection-pending"
                        or type(delay) is not int or not 0 < delay <= 10000):
                    raise
                until = min(deadline, time.monotonic() + delay / 1000)
                while time.monotonic() < until:
                    self._check(deadline, cancel_source)
                    time.sleep(min(0.1, max(0, until - time.monotonic())))

    def prepare(self, *, timeout: float, cancel_source) -> None:
        ws = self._connect(time.monotonic() + timeout, cancel_source)
        ws.close()

    def run(self, params: dict, *, timeout: float, cancel_source, on_event) -> dict:
        deadline = time.monotonic() + timeout
        ws = self._connect(deadline, cancel_source)
        accepted = None
        request_id = None
        settled = False
        try:
            request_id, accepted = self._submit(ws, params, deadline, cancel_source, on_event)
            if accepted.get("status") != "accepted" or not isinstance(accepted.get("runId"), str):
                raise ValueError(f"OpenClaw did not accept the turn: {accepted}")
            result = self._response(ws, request_id, deadline, cancel_source, on_event)
            settled = True
            if (result.get("runId") != accepted["runId"] or result.get("status") != "ok"
                    or not isinstance(result.get("result"), dict)):
                raise RuntimeError(f"OpenClaw turn failed: {result}")
            return result["result"]
        except BaseException:
            if accepted is not None and not settled:
                # Let the native runtime settle its durable active-turn record
                # before releasing the process. A hard kill alone races startup
                # recovery against the next admitted turn.
                self._abort(ws, request_id, accepted, params["sessionKey"])
            raise
        finally:
            ws.close()

    def _abort(self, ws, turn_request_id: str, accepted: dict, session_key: str) -> None:
        deadline = time.monotonic() + 5
        abort_id = self._send(ws, "chat.abort", {"sessionKey": session_key, "runId": accepted["runId"]})
        acknowledged = settled = False
        while not (acknowledged and settled):
            frame = self._receive(ws, deadline, None)
            if frame.get("id") == turn_request_id:
                settled = frame.get("payload", {}).get("status") != "accepted"
            elif frame.get("id") == abort_id:
                if frame.get("ok") is not True or not isinstance(frame.get("payload"), dict):
                    raise RuntimeError(f"OpenClaw abort failed: {frame}")
                payload = frame["payload"]
                # An already completed run may correctly report aborted=false;
                # its final turn response is still required before shutdown.
                if type(payload.get("aborted")) is not bool:
                    raise ValueError("Invalid OpenClaw abort acknowledgement.")
                acknowledged = True

    def close(self) -> None:
        if self.job:
            self.job.close()
            self.process.wait(timeout=10)
        else:
            stop_process(self.process)
        self.reader.join(timeout=2)
        self.process.stdout.close()
