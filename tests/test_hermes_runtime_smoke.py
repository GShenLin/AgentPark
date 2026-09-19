"""Real Hermes SDK tool execution against a local model stub; no paid model requests."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.harness.contracts import HarnessContext
from src.harness.registry import create_adapter


@pytest.mark.skipif(not os.environ.get("AGENTPARK_TEST_HERMES_PYTHON"), reason="Set Hermes environment Python")
@pytest.mark.parametrize("provider_type,effort", [("openai", ""), ("deepseek", "high"), ("deepseek", "max")])
def test_hermes_executes_tool_and_projects_live_events(tmp_path, monkeypatch, provider_type, effort):
    from src.harness.adapters import hermes_agent
    work = tmp_path / "work"
    work.mkdir()
    target = work / "read-me.txt"
    target.write_text("HERMES_TOOL_FILE_CONTENT", encoding="utf-8")
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(payload)
            has_result = any(message["role"] == "tool" for message in payload["messages"])
            delta = {"role": "assistant", "content": "HERMES_TOOL_OK."} if has_result else {
                "role": "assistant", "tool_calls": [{"index": 0, "id": "read-one", "type": "function",
                    "function": {"name": "read_file", "arguments": json.dumps({"path": str(target)})}}]}
            chunks = [
                {"id": "chat-test", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {"id": "chat-test", "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if "tool_calls" in delta else "stop"}],
                 "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}},
            ]
            data = ("".join("data: " + json.dumps(item) + "\n\n" for item in chunks) + "data: [DONE]\n\n").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {"id": "p", "type": provider_type, "model": "first", "models": ["first", "second"],
              "supportmode": ["chat"], "apiKey": "stub-secret", "authMode": "api_key",
              "baseUrl": f"http://127.0.0.1:{server.server_port}/v1"}
    monkeypatch.setattr("src.config_loader.ConfigLoader.get_provider_config", lambda self, key: dict(config))
    monkeypatch.setattr(hermes_agent, "command_argv", lambda key: [os.environ["AGENTPARK_TEST_HERMES_PYTHON"]])
    captured = []
    monkeypatch.setattr("src.harness.adapters.cli_session.stream_callback", lambda values: captured.append)
    node = tmp_path / "node"
    node.mkdir()
    context = HarnessContext(str(node / "config.json"), str(node),
                             {"provider_id": "p", "model": "second", "working_path": str(work), "timeout_seconds": 90,
                              "reasoning_effort": effort})
    try:
        result = create_adapter("hermes_agent").run("Read read-me.txt and reply HERMES_TOOL_OK.", context)
        assert result.text == "HERMES_TOOL_OK."
        assert len(received) == 2
        assert "HERMES_TOOL_FILE_CONTENT" in json.dumps(received[-1]["messages"])
        assert all(item["model"] == "second" for item in received)
        tools = [event for event in captured if event["type"] in {"tool_call_start", "tool_call_end"}]
        assert len(tools) == 2
        assert tools[0]["call_id"] == tools[1]["call_id"]
        assert tools[0]["name"] == "read_file"
        assert tools[1]["status"] == "completed"
        state_dir = next((node / ".harness" / "hermes_agent").glob("*/conversation.json")).parent
        snapshot = json.loads((state_dir / "conversation.json").read_text(encoding="utf-8"))
        session_id = snapshot["session_id"]

        def assert_native_history():
            snapshot = json.loads((state_dir / "conversation.json").read_text(encoding="utf-8"))
            assert snapshot["session_id"] == session_id
            with closing(sqlite3.connect(state_dir / "home" / "state.db")) as db:
                rows = db.execute("SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
                                  (session_id,)).fetchall()
                assert rows == [(item["role"], item.get("content")) for item in snapshot["messages"]]
                assert db.execute("SELECT ended_at FROM sessions WHERE id = ?", (session_id,)).fetchone() == (None,)
            return snapshot

        assert_native_history()
        with closing(sqlite3.connect(state_dir / "home" / "state.db")) as db, db:
            db.execute("UPDATE sessions SET ended_at = 1, end_reason = 'agent_close' WHERE id = ?", (session_id,))
        # A fresh subprocess must send the preceding transcript to the provider and
        # persist its own turn even when no recall tool ever opens the database.
        for question in ("What did the file say?", "What did we just discuss?"):
            before = json.loads((state_dir / "conversation.json").read_text(encoding="utf-8"))
            result = create_adapter("hermes_agent").run(question, context)
            assert result.text == "HERMES_TOOL_OK."
            wire_history = json.dumps(received[-1]["messages"])
            assert "HERMES_TOOL_FILE_CONTENT" in wire_history
            assert "Read read-me.txt" in wire_history
            assert "excludes the current live session" in wire_history
            after = assert_native_history()
            assert len(after["messages"]) == len(before["messages"]) + 2

        # Reproduce an existing snapshot with an unpersisted tail: the adapter must
        # repair it before passing it as already-durable history to Hermes.
        history = assert_native_history()
        history["messages"].extend([
            {"role": "user", "content": "SNAPSHOT_ONLY_QUESTION"},
            {"role": "assistant", "content": "SNAPSHOT_ONLY_ANSWER"},
        ])
        (state_dir / "conversation.json").write_text(json.dumps(history), encoding="utf-8")
        create_adapter("hermes_agent").run("Continue from the saved snapshot.", context)
        assert_native_history()
        assert "SNAPSHOT_ONLY_ANSWER" in json.dumps(received[-1]["messages"])
        # AgentPark must not introduce an output budget on this Hermes route.
        # Inspect the actual provider wire payload after SDK and gateway conversion.
        for payload in received:
            assert not {"max_tokens", "max_completion_tokens", "max_output_tokens"}.intersection(payload)
            if effort:
                assert payload["reasoning_effort"] == effort
        if provider_type == "openai":
            from types import SimpleNamespace
            from src.web_backend.node_memory_reset import reset_node_memory
            (node / "config.json").write_text("{}", encoding="utf-8")
            memories = state_dir / "home" / "memories"
            memories.mkdir(exist_ok=True)
            (memories / "MEMORY.md").write_text("OLD_NATIVE_MEMORY_PROBE", encoding="utf-8")
            reset_node_memory(core=SimpleNamespace(node_runs={}), config_path=context.config_path,
                node_directory=str(node), memory_path=str(node / "memory.md"),
                messages_path=str(node / "messages.jsonl"))
            assert not state_dir.exists()
            first_new_request = len(received)
            create_adapter("hermes_agent").run("Start a fresh conversation.", context)
            new_wire = json.dumps(received[first_new_request]["messages"])
            for old_text in ("SNAPSHOT_ONLY_ANSWER", "OLD_NATIVE_MEMORY_PROBE", "Read read-me.txt",
                             "What did we just discuss?", "HERMES_TOOL_FILE_CONTENT"):
                assert old_text not in new_wire
            new_state = next((node / ".harness" / "hermes_agent").glob("*/conversation.json"))
            assert json.loads(new_state.read_text(encoding="utf-8"))["session_id"] != session_id
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
