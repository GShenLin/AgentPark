from __future__ import annotations

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer

import pytest

from src.codex_runtime.live_bridge import CodexLiveBridge
from src.codex_runtime.provider_gateway import CodexProviderGateway
from src.codex_runtime.session_manager import CodexSessionManager
from src.codex_runtime.session_manager import CodexSessionSpec


@pytest.mark.skipif(shutil.which("codex") is None and shutil.which("codex.cmd") is None, reason="Codex CLI is not installed")
def test_real_codex_app_server_uses_provider_id_chat_conversion_and_runs_tool(tmp_path, monkeypatch):
    upstream_payloads = []

    class ChatHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            length = int(self.headers["Content-Length"])
            upstream_payloads.append(json.loads(self.rfile.read(length).decode("utf-8")))
            if len(upstream_payloads) == 1:
                chunks = [
                    {
                        "id": "chat-1",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "tool_calls": [
                                            {
                                                "index": 0,
                                                "id": "call-exec-1",
                                                "type": "function",
                                                "function": {
                                                    "name": "exec",
                                                    "arguments": json.dumps(
                                                        {"input": "text('CODEX_TOOL_OK');"},
                                                        separators=(",", ":"),
                                                    ),
                                                },
                                        }
                                    ]
                                },
                            }
                        ],
                    },
                    {"id": "chat-1", "choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
                ]
            else:
                chunks = [
                    {"id": "chat-2", "choices": [{"index": 0, "delta": {"role": "assistant"}}]},
                    {"id": "chat-2", "choices": [{"index": 0, "delta": {"reasoning_content": "Mock reasoning"}}]},
                    {"id": "chat-2", "choices": [{"index": 0, "delta": {"content": "Tool completed via ProviderID"}}]},
                    {"id": "chat-2", "choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 5}},
                ]
            body = "".join(
                f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n" for chunk in chunks
            ) + "data: [DONE]\n\n"
            encoded = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format, *args):
            return

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), ChatHandler)
    upstream.daemon_threads = True
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    host, port = upstream.server_address

    config_path = tmp_path / "modelProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "mock-chat": {
                        "type": "deepseek",
                        "baseUrl": f"http://{host}:{port}/v1",
                        "apiKey": "test",
                        "model": "gpt-5.1-codex",
                        "supportmode": ["chat"],
                        "streamEnabled": True,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    gateway = CodexProviderGateway()
    manager = CodexSessionManager(gateway=gateway)
    events = []
    bridge = CodexLiveBridge(events.append)
    try:
        result = manager.run_turn(
            CodexSessionSpec(
                session_key="smoke",
                provider_id="mock-chat",
                model="gpt-5.1-codex",
                command="codex",
                cwd=str(tmp_path),
                sandbox="workspace-write",
                state_path=str(tmp_path / "codex_session.json"),
                reasoning_effort="high",
            ),
            "Reply with the mock response.",
            event_handler=bridge.handle,
        )
        bridge.emit_done(result)
    finally:
        manager.close_all()
        gateway.close()
        upstream.shutdown()
        upstream.server_close()
        upstream_thread.join(timeout=2)

    assert result == "Tool completed via ProviderID"
    assert len(upstream_payloads) == 2
    assert upstream_payloads[0]["model"] == "gpt-5.1-codex"
    assert any(message.get("role") == "tool" for message in upstream_payloads[1]["messages"])
    assert any(event.get("type") == "node_message_delta" for event in events)
    assert any(event.get("type") == "node_thinking_delta" and event.get("provider") == "codex" for event in events)
    assert any(event.get("type") == "tool_call_start" and event.get("name") == "exec" for event in events)
    assert any(event.get("type") == "tool_call_end" and event.get("status") == "completed" for event in events)
    gateway_requests = [
        json.loads(event["message"])
        for event in events
        if event.get("type") == "runtime_notice" and event.get("stage") == "provider_gateway_request"
    ]
    assert [request["requested_model"] for request in gateway_requests] == ["gpt-5.6-sol", "gpt-5.6-sol"]
    assert [request["provider_model"] for request in gateway_requests] == ["gpt-5.1-codex", "gpt-5.1-codex"]
    completed_requests = [
        json.loads(event["message"])
        for event in events
        if event.get("type") == "runtime_notice" and event.get("stage") == "provider_request_completed"
    ]
    assert [request["usage"]["input_tokens"] for request in completed_requests] == [10, 20]
    assert [request["usage"]["output_tokens"] for request in completed_requests] == [5, 5]
    assert events[-1]["type"] == "node_message_done"
