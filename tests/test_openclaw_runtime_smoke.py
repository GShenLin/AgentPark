"""Real OpenClaw event subscription with a gated local model, no remote calls."""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.harness.contracts import HarnessContext
from src.harness.registry import create_adapter
from src.web_backend.node_runtime_event_sink import NodeRuntimeEventSink


@pytest.mark.skipif(not os.environ.get("AGENTPARK_TEST_OPENCLAW_ENTRY"), reason="Set installed OpenClaw entry")
@pytest.mark.parametrize("provider_type,effort,tool_name", [("openai", "", "read"), ("openai", "minimal", "read"),
    ("openai", "xhigh", "read"), ("deepseek", "high", "read"), ("deepseek", "max", "read"), ("openai", "", "write")])
def test_openclaw_emits_tools_and_text_before_model_completion(tmp_path, monkeypatch, provider_type, effort, tool_name):
    tool_started, tool_ended, text_seen = (threading.Event() for _ in range(3))
    input_seen = threading.Event()
    received, events, gates = [], [], []
    workspace = tmp_path / "work"
    workspace.mkdir()
    target = workspace / "read-me.txt"
    target.write_text("OPENCLAW_FILE_CONTENT", encoding="utf-8")
    written_content = "GENERATED_LINE_ONE\nGENERATED_LINE_TWO\n"

    def capture(event):
        events.append(event)
        sink.handle(event)
        if event["type"] == "tool_call_start":
            tool_started.set()
        if event["type"] == "tool_call_end":
            tool_ended.set()
        if event["type"] == "node_message_delta" and "STREAM_BEFORE_DONE" in event["text"]:
            text_seen.set()
        if event.get("stage") == "openclaw_tool_input":
            input_seen.set()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(payload)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            if tool_name == "write":
                self.stream_responses(payload)
                return
            has_result = any(item["role"] == "tool" for item in payload["messages"])
            if has_result:
                gates.append(tool_started.wait(10) and tool_ended.wait(10))
                delta = {"role": "assistant", "content": "STREAM_BEFORE_DONE"}
            else:
                arguments = json.dumps({"path": str(target)})
                delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": "read-one", "type": "function",
                    "function": {"name": tool_name, "arguments": arguments}}]}
            self.chunk({"delta": delta, "finish_reason": None})
            if has_result:
                # Do not finish the model response until AgentPark received a
                # live text event. Buffered-at-exit implementations fail here.
                gates.append(text_seen.wait(10))
            self.chunk({"delta": {}, "finish_reason": "stop" if has_result else "tool_calls"})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

        def chunk(self, choice):
            self.wfile.write(("data: " + json.dumps({"id": "chat-test", "choices": [{"index": 0, **choice}]}) + "\n\n").encode())
            self.wfile.flush()

        def stream_responses(self, payload):
            has_result = any(item["type"] == "function_call_output" for item in payload["input"])
            response_id = "resp-final" if has_result else "resp-tool"
            self.event("response.created", response={"id": response_id, "status": "in_progress", "output": []})
            if has_result:
                gates.append(tool_started.wait(10) and tool_ended.wait(10))
                item = {"type": "message", "id": "msg-1", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": "STREAM_BEFORE_DONE", "annotations": []}]}
                self.event("response.output_item.added", output_index=0, item={**item, "status": "in_progress", "content": []})
                fields = {"output_index": 0, "item_id": item["id"], "content_index": 0}
                self.event("response.content_part.added", **fields, part={"type": "output_text", "text": "", "annotations": []})
                self.event("response.output_text.delta", **fields, delta="STREAM_BEFORE_DONE")
                gates.append(text_seen.wait(10))
                self.event("response.output_text.done", **fields, text="STREAM_BEFORE_DONE")
                self.event("response.content_part.done", **fields, part=item["content"][0])
            else:
                arguments = json.dumps({"path": str(target), "content": written_content})
                item = {"type": "function_call", "id": "fc-1", "call_id": "write-one", "name": "write",
                        "arguments": arguments, "status": "completed"}
                fields = {"output_index": 0, "item_id": item["id"]}
                self.event("response.output_item.added", output_index=0, item={**item, "status": "in_progress", "arguments": ""})
                self.event("response.function_call_arguments.delta", **fields, delta=arguments[:-2])
                gates.append(input_seen.wait(10) and not tool_started.is_set())
                self.event("response.function_call_arguments.delta", **fields, delta=arguments[-2:])
                self.event("response.function_call_arguments.done", **fields, arguments=arguments)
            self.event("response.output_item.done", output_index=0, item=item)
            self.event("response.completed", response={"id": response_id, "status": "completed", "output": [item],
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}})

        def event(self, event_type, **fields):
            data = json.dumps({"type": event_type, **fields})
            self.wfile.write((f"event: {event_type}\ndata: {data}\n\n").encode())
            self.wfile.flush()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    provider = {"id": "p", "type": provider_type, "model": "test-model", "models": ["test-model"],
                "supportmode": ["chat"], "apiKey": "stub-secret", "authMode": "api_key",
                "baseUrl": f"http://127.0.0.1:{server.server_port}/v1"}
    if tool_name == "write":
        provider["responsesApi"] = True
    monkeypatch.setattr("src.config_loader.ConfigLoader.get_provider_config", lambda self, key: dict(provider))
    monkeypatch.setattr("src.harness.adapters.openclaw.command_argv",
                        lambda key: ["node", os.environ["AGENTPARK_TEST_OPENCLAW_ENTRY"]])
    monkeypatch.setattr("src.harness.adapters.cli_session.stream_callback", lambda values: capture)
    node = tmp_path / "node"
    node.mkdir()
    (node / "config.json").write_text(json.dumps({"reasoning_effort": effort}), encoding="utf-8")
    process_events = []
    sink = NodeRuntimeEventSink(graph_id="default", node_id="openclaw-test", node_type_id="openclaw_node",
        config_path=str(node / "config.json"), trace_id="test-run", depth=0, stream_last_text="",
        log_graph_event=lambda graph, event, **fields: process_events.append({"event": event, **fields}),
        append_tool_call_entry=lambda *args: None, append_runtime_log=lambda *args, **fields: None)
    context = HarnessContext(str(node / "config.json"), str(node),
        {"provider_id": "p", "model": "test-model", "working_path": str(workspace), "timeout_seconds": 90})
    try:
        result = create_adapter("openclaw").run(f"Use {tool_name} on read-me.txt, then answer.", context)
        assert result.text == "STREAM_BEFORE_DONE"
        assert len(received) == 2
        if effort:
            assert all(payload.get("reasoning_effort") == effort for payload in received)
        assert gates == ([True, True, True] if tool_name == "write" else [True, True])
        tools = result.metadata["response_metadata"]["runtime_tool_calls"]
        assert len(tools) == 1 and tools[0]["name"] == tool_name and tools[0]["status"] == "completed"
        if tool_name == "write":
            assert target.read_text(encoding="utf-8") == written_content
            assert next(i for i, e in enumerate(events) if e.get("stage") == "openclaw_tool_input") < next(
                i for i, e in enumerate(events) if e["type"] == "tool_call_start")
        else:
            assert "OPENCLAW_FILE_CONTENT" in tools[0]["result_preview"]
        assert any(item.get("stage") == "openclaw_lifecycle" for item in events)
        assert events[-1]["type"] == "node_message_done"
        process_types = [item["event"] for item in process_events]
        assert process_types.index("tool_call_start") < process_types.index("node_message_done")
        assert process_types.index("tool_call_end") < process_types.index("node_message_done")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
