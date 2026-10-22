"""Opt-in native continuity, warm reuse and cancellation with a local model."""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import uuid

import pytest

from src.harness.contracts import HarnessContext
from src.harness.openclaw_gateway import OpenClawGateway
from src.harness.openclaw_session import OpenClawSessions
from src.harness.process import run_process
from src.harness.registry import create_adapter
from src.runtime_cancellation import CancellationRequested

pytestmark = pytest.mark.skipif(not os.environ.get("AGENTPARK_TEST_OPENCLAW_ENTRY"), reason="Set installed OpenClaw entry")


@pytest.fixture
def native(tmp_path, monkeypatch):
    payloads, children = [], []
    cancel = threading.Event()
    cancel_next = [False]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payloads.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            if cancel_next[0]:
                cancel_next[0] = False
                cancel.set()
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            chunks = [{"id": "chat", "choices": [{"index": 0, "delta": {"role": "assistant", "content": "NATIVE_OK"}, "finish_reason": None}]},
                      {"id": "chat", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}]
            body = ("".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    provider = {"id": "p", "type": "openai", "model": "test-model", "models": ["test-model"],
                "supportmode": ["chat"], "apiKey": "stub", "authMode": "api_key",
                "baseUrl": f"http://127.0.0.1:{server.server_port}/v1"}
    monkeypatch.setattr("src.config_loader.ConfigLoader.get_provider_config", lambda self, key: dict(provider))
    manager = OpenClawSessions()

    def factory(*args, **kwargs):
        child = OpenClawGateway(*args, **kwargs)
        children.append(child)
        return child

    manager.client_factory = factory
    monkeypatch.setattr(OpenClawSessions, "instance", classmethod(lambda cls: manager))
    context = HarnessContext(str(tmp_path / "config.json"), str(tmp_path), {
        "provider_id": "p", "model": "test-model", "timeout_seconds": 90, "cancel_event": cancel})
    try:
        yield manager, context, payloads, children, cancel, cancel_next
    finally:
        manager.close_all()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_existing_local_cli_session_resumes_then_reuses_gateway(native):
    manager, context, payloads, children, _, _ = native
    factory = manager.client_factory

    def seed_legacy(argv, **kwargs):
        state = kwargs["env"]["OPENCLAW_STATE_DIR"]
        result = run_process([*argv, "agent", "--local", "--json", "--session-id",
            str(uuid.uuid5(uuid.NAMESPACE_URL, state)), "--message", "LEGACY_HISTORY_MARKER: Say NATIVE_OK.",
            "--timeout", "90"], cwd=kwargs["cwd"], env=kwargs["env"], timeout=90)
        assert "NATIVE_OK" in result
        return factory(argv, **kwargs)

    manager.client_factory = seed_legacy
    adapter = create_adapter("openclaw")
    assert adapter.run("WARM_MARKER_1: Say NATIVE_OK.", context).text == "NATIVE_OK"
    assert adapter.run("WARM_MARKER_2: Say NATIVE_OK.", context).text == "NATIVE_OK"
    assert len(children) == 1 and len(payloads) == 3
    assert "LEGACY_HISTORY_MARKER" in json.dumps(payloads[-1]["messages"])
    assert "WARM_MARKER_1" in json.dumps(payloads[-1]["messages"])
    manager.close_under(context.node_directory)
    assert children[0].process.poll() is not None


def test_cancel_admitted_turn_closes_process_then_native_state_can_resume(native):
    manager, context, payloads, children, cancel, cancel_next = native
    adapter = create_adapter("openclaw")
    cancel_next[0] = True
    with pytest.raises(CancellationRequested):
        adapter.run("CANCEL_MARKER: Say NATIVE_OK.", context)
    assert len(children) == 1 and children[0].process.poll() is not None
    assert len(payloads) == 1
    cancel.clear()
    assert adapter.run("RESUME_MARKER: Say NATIVE_OK.", context).text == "NATIVE_OK"
    assert len(children) == 2 and len(payloads) == 2, [
        [message.get("content") for message in payload["messages"] if message.get("role") == "user"][-1:]
        for payload in payloads]
