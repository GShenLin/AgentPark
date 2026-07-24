from __future__ import annotations

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer

from src.codex_runtime.provider_gateway import CodexProviderGateway


def test_gateway_transparently_forwards_responses_for_non_openai_provider_type(monkeypatch):
    received = []
    raw_sse = (
        'event: response.created\ndata: {"type":"response.created","response":{"id":"resp-native"}}\n\n'
        'event: response.completed\ndata: {"type":"response.completed","response":{"id":"resp-native"}}\n\n'
    ).encode("utf-8")

    class UpstreamHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received.append(json.loads(self.rfile.read(length).decode("utf-8")))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw_sse)))
            self.end_headers()
            self.wfile.write(raw_sse)

        def log_message(self, _format, *args):
            return

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    host, port = upstream.server_address
    config = {
        "type": "claude",
        "responsesApi": True,
        "baseUrl": f"http://{host}:{port}/v1",
        "apiKey": "secret",
        "authMode": "api_key",
        "model": "native-responses-model",
        "supportmode": ["chat"],
    }
    monkeypatch.setattr("src.codex_runtime.provider_gateway.ConfigLoader.get_provider_config", lambda _self, _id: dict(config))
    gateway = CodexProviderGateway()
    lease = gateway.register("native-provider")
    observations = []
    try:
        body = json.dumps({"model": "codex-request-model", "input": "hello", "stream": True}).encode("utf-8")
        request = urllib.request.Request(
            f"{lease.base_url}/responses",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with gateway.observe_requests(lease.token, observations.append):
            with urllib.request.urlopen(request, timeout=5) as response:
                forwarded = response.read()
    finally:
        gateway.release(lease.token)
        gateway.close()
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=2)

    assert forwarded == raw_sse
    assert received[0]["model"] == "native-responses-model"
    assert observations == [
        {
            "method": "agentpark/providerGateway/request",
            "params": {
                "request_index": 1,
                "provider_id": "native-provider",
                "requested_model": "codex-request-model",
                "provider_model": "native-responses-model",
                "payload_chars": len(json.dumps(received[0], ensure_ascii=False, separators=(",", ":"))),
                "approx_payload_tokens": (
                    len(json.dumps(received[0], ensure_ascii=False, separators=(",", ":"))) + 3
                )
                // 4,
                "input_item_count": 1,
                "tools_included_count": 0,
                "instructions_chars": 0,
                "stream": True,
            },
        }
    ]

