"""Published MiniMax CLI, real file tool, local deterministic model; no paid requests."""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.harness.contracts import HarnessContext
from src.harness.registry import create_adapter


@pytest.mark.skipif(not os.environ.get("AGENTPARK_TEST_MCODE_ENTRY"), reason="Set MiniMax Code JS entry")
@pytest.mark.parametrize("tool_name", ["read", "write", "bash"])
def test_minimax_file_tools_and_explicit_reasoning(monkeypatch, tool_name):
    received = []
    failures = []
    emitted = []
    with TemporaryDirectory(prefix="ap-mct-") as directory:
        root = Path(directory)
        work = root / "work"
        work.mkdir()
        target = work / "read-me.txt"
        target.write_text("MINIMAX_TOOL_FILE_CONTENT", encoding="utf-8")

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append(payload)
                has_result = any(message["role"] == "tool" for message in payload["messages"])
                if has_result:
                    delta = {"role": "assistant", "content": "MINIMAX_TOOL_OK"}
                else:
                    tools = {item["function"]["name"]: item["function"] for item in payload["tools"]}
                    if tool_name not in tools:
                        failures.append(list(tools))
                        self.send_error(400, "Missing requested tool")
                        return
                    arguments = {"path": str(target)}
                    if tool_name == "write":
                        arguments["content"] = "MINIMAX_WRITTEN_CONTENT"
                    elif tool_name == "bash":
                        arguments = {"command": "echo MINIMAX_COMMAND_OK"}
                    delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": "read-one", "type": "function",
                        "function": {"name": tool_name, "arguments": json.dumps(arguments)}}]}
                chunks = [
                    {"id": "chat-tool", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                    {"id": "chat-tool", "choices": [{"index": 0, "delta": {},
                        "finish_reason": "stop" if has_result else "tool_calls"}],
                     "usage": {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}},
                ]
                body = ("".join("data: " + json.dumps(item) + "\n\n" for item in chunks) + "data: [DONE]\n\n").encode()
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
        config = {"id": "p", "type": "openai", "model": "selected", "models": ["selected"],
                  "supportmode": ["chat"], "apiKey": "local-stub-secret", "authMode": "api_key",
                  "baseUrl": f"http://127.0.0.1:{server.server_port}/v1"}
        monkeypatch.setattr("src.config_loader.ConfigLoader.get_provider_config", lambda self, key: dict(config))
        monkeypatch.setattr("src.harness.adapters.minimax_code.command_argv",
                            lambda key: ["node", os.environ["AGENTPARK_TEST_MCODE_ENTRY"]])
        node = root / "node"
        node.mkdir()
        context = HarnessContext(str(node / "config.json"), str(node), {
            "provider_id": "p", "model": "selected", "working_path": str(work), "reasoning_effort": "high",
            "stream_callback": emitted.append, "timeout_seconds": 60,
            "permission_mode": "bypassPermissions" if tool_name == "bash" else "auto"})
        try:
            prompt = ("Read read-me.txt and report its content." if tool_name == "read" else
                      "Write MINIMAX_WRITTEN_CONTENT to read-me.txt. This test fixture is disposable.")
            if tool_name == "bash":
                prompt = "Run echo MINIMAX_COMMAND_OK in the disposable working directory."
            result = create_adapter("minimax_code").run(prompt, context)
            assert not failures, failures
            assert result.text == "MINIMAX_TOOL_OK"
            assert len(received) == 2
            assert all(item["model"] == "selected" and item["reasoning_effort"] == "high" for item in received)
            if tool_name == "read":
                assert "MINIMAX_TOOL_FILE_CONTENT" in json.dumps(received[-1]["messages"])
            elif tool_name == "write":
                assert target.read_text(encoding="utf-8") == "MINIMAX_WRITTEN_CONTENT"
            else:
                assert "MINIMAX_COMMAND_OK" in json.dumps(received[-1]["messages"])
            tools = [event for event in emitted if event["type"] == "tool_call_end"]
            assert len(tools) == 1 and tools[0]["status"] == "completed"
            assert any(event["type"] == "node_message_delta" for event in emitted)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
