from __future__ import annotations

from collections import deque
import json
import threading
import time
from types import SimpleNamespace

import pytest

from src.harness.openclaw_gateway import GatewayError, OpenClawGateway
from src.runtime_cancellation import CancellationRequested


class Socket:
    def __init__(self, *, error=None, malformed=False, pending=None):
        self.frames = deque([{"type": "event", "event": "connect.challenge", "payload": {"nonce": "n", "ts": 1}}])
        self.sent = []
        self.closed = False
        self.error, self.malformed, self.pending = error, malformed, pending

    def send(self, raw):
        request = json.loads(raw)
        self.sent.append(request)
        base = {"type": "res", "id": request["id"], "ok": True}
        if request["method"] == "chat.abort":
            turn_id = next(item["id"] for item in self.sent if item["method"] == "agent")
            self.frames.append({"type": "res", "id": turn_id, "ok": False,
                                "error": {"code": "ABORTED"}})
            self.frames.append({**base, "payload": {"aborted": True}})
            return
        if request["method"] == "connect":
            if self.error:
                self.frames.append({**base, "ok": False, "error": self.error})
            else:
                self.frames.append({**base, "payload": {"type": "hello-ok", "protocol": 4,
                                                       "features": {"methods": ["agent"]}}})
        else:
            self.frames.append({**base, "payload": {"status": "accepted", "runId": "run"}})
            if self.pending:
                return
            self.frames.append({"type": "event", "event": "agent", "payload": {
                "runId": "run", "seq": 1, "stream": "assistant", "data": {"delta": "hello"}}})
            self.frames.append({**base, "payload": {"status": "ok", "runId": "wrong" if self.malformed else "run",
                                                   "result": {"payloads": [{"text": "hello"}]}}})

    def recv(self, timeout):
        if self.frames:
            return json.dumps(self.frames.popleft())
        if self.pending:
            self.pending()
        raise TimeoutError()

    def close(self):
        self.closed = True


def client(monkeypatch, sockets):
    runtime = OpenClawGateway.__new__(OpenClawGateway)
    runtime.url, runtime.token = "ws://127.0.0.1:12345", "secret"
    runtime.process = SimpleNamespace(poll=lambda: None)
    calls = []

    def connect(url, **kwargs):
        calls.append((url, kwargs))
        return sockets.pop(0)

    monkeypatch.setattr("src.harness.openclaw_gateway.connect", connect)
    return runtime, calls


def test_direct_gateway_waits_for_final_and_streams_before_it(monkeypatch):
    ws = Socket()
    runtime, calls = client(monkeypatch, [ws])
    events = []
    result = runtime.run({"message": "test"}, timeout=1, cancel_source=None, on_event=events.append)
    assert result == {"payloads": [{"text": "hello"}]}
    assert events[0]["data"] == {"delta": "hello"}
    assert ws.closed and len(ws.sent) == 2
    assert calls[0][1]["proxy"] is None
    assert ws.sent[0]["params"]["caps"] == ["tool-events"]


def test_only_explicit_startup_sidecar_response_is_retried(monkeypatch):
    starting = Socket(error={"code": "UNAVAILABLE", "retryable": True, "retryAfterMs": 1,
                             "details": {"reason": "startup-sidecars"}})
    ready = Socket()
    runtime, calls = client(monkeypatch, [starting, ready])
    runtime.run({}, timeout=1, cancel_source=None, on_event=None)
    assert len(calls) == 2 and starting.closed and ready.closed


@pytest.mark.parametrize("error", [{"code": "NOT_PAIRED"}, {"code": "UNAVAILABLE", "retryable": True},
    {"code": "UNAVAILABLE", "retryable": True, "retryAfterMs": True, "details": {"reason": "startup-sidecars"}}])
def test_auth_and_invalid_startup_failures_are_not_retried(monkeypatch, error):
    ws = Socket(error=error)
    runtime, calls = client(monkeypatch, [ws])
    with pytest.raises(GatewayError):
        runtime.run({}, timeout=1, cancel_source=None, on_event=None)
    assert len(calls) == 1 and ws.closed


def test_mismatched_run_result_is_rejected(monkeypatch):
    ws = Socket(malformed=True)
    runtime, _ = client(monkeypatch, [ws])
    with pytest.raises(RuntimeError, match="turn failed"):
        runtime.run({}, timeout=1, cancel_source=None, on_event=None)
    assert ws.closed


def test_cancel_waiting_turn_closes_socket_without_replaying(monkeypatch):
    cancel = threading.Event()
    ws = Socket(pending=cancel.set)
    runtime, calls = client(monkeypatch, [ws])
    with pytest.raises(CancellationRequested):
        runtime.run({"sessionKey": "session"}, timeout=1, cancel_source=cancel, on_event=None)
    assert len(calls) == 1 and [item["method"] for item in ws.sent] == ["connect", "agent", "chat.abort"]
    assert ws.closed


def test_timeout_is_a_single_budget_for_connection_and_turn(monkeypatch):
    ws = Socket(pending=lambda: time.sleep(0.01))
    runtime, _ = client(monkeypatch, [ws])
    with pytest.raises(TimeoutError):
        runtime.run({"sessionKey": "session"}, timeout=0.02, cancel_source=None, on_event=None)
    assert ws.closed


def test_pre_admission_database_readiness_preserves_idempotency_key(monkeypatch):
    class Preparing(Socket):
        def send(self, raw):
            request = json.loads(raw)
            if request["method"] == "agent" and len(self.sent) == 1:
                self.sent.append(request)
                self.frames.append({"type": "res", "id": request["id"], "ok": False, "error": {
                    "code": "UNAVAILABLE", "retryable": True, "retryAfterMs": 1,
                    "details": {"code": "agent-database-inspection-pending"}}})
            else:
                super().send(raw)

    ws = Preparing()
    runtime, _ = client(monkeypatch, [ws])
    runtime.run({"idempotencyKey": "same"}, timeout=1, cancel_source=None, on_event=None)
    assert [message["params"] for message in ws.sent[1:]] == [{"idempotencyKey": "same"}] * 2


def test_cancellation_racing_acceptance_still_aborts_the_exact_run(monkeypatch):
    cancel = threading.Event()

    class CancelOnSend(Socket):
        def send(self, raw):
            super().send(raw)
            if json.loads(raw)["method"] == "agent":
                cancel.set()

    ws = CancelOnSend()
    runtime, _ = client(monkeypatch, [ws])
    with pytest.raises(CancellationRequested):
        runtime.run({"sessionKey": "session", "idempotencyKey": "run"},
                    timeout=1, cancel_source=cancel, on_event=None)
    assert ws.sent[-1]["params"] == {"sessionKey": "session", "runId": "run"}
    assert ws.closed
