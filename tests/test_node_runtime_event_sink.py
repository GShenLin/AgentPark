import json

import pytest

from src.web_backend.node_runtime_event_sink import NodeRuntimeEventSink


def _read_config(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_sink(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"node_id": "agent1"}, ensure_ascii=False), encoding="utf-8")
    logs = []
    tool_entries = []
    sink = NodeRuntimeEventSink(
        graph_id="default",
        node_id="agent1",
        node_type_id="agent_node",
        config_path=str(config_path),
        trace_id="trace-1",
        depth=2,
        stream_last_text="hello",
        log_graph_event=lambda graph_id, event, **fields: logs.append(
            {"graph_id": graph_id, "event": event, **fields}
        ),
        append_tool_call_entry=lambda graph_id, node_id, event: tool_entries.append(
            {"graph_id": graph_id, "node_id": node_id, "event": dict(event)}
        ),
    )
    return sink, config_path, logs, tool_entries


def test_node_runtime_event_sink_updates_stream_text_and_done_log(tmp_path):
    sink, config_path, logs, tool_entries = _build_sink(tmp_path)

    sink.handle({"type": "node_message_delta", "text": "hello world"})
    sink.handle({"type": "node_message_done", "text": "hello world!"})

    payload = _read_config(config_path)
    assert payload["last_message"] == "hello world!"
    assert sink.stream_last_text == "hello world!"
    assert logs[-1]["event"] == "node_message_done"
    assert logs[-1]["output_preview"] == "hello world!"
    assert tool_entries == []


def test_node_runtime_event_sink_rejects_unknown_event_type(tmp_path):
    sink, _config_path, _logs, _tool_entries = _build_sink(tmp_path)

    with pytest.raises(ValueError, match="unsupported node runtime event type"):
        sink.handle({"type": "delta", "text": "legacy"})


def test_node_runtime_event_sink_records_runtime_notice(tmp_path):
    sink, config_path, logs, _tool_entries = _build_sink(tmp_path)

    sink.handle(
        {
            "type": "runtime_notice",
            "message": "Calling tool: read_file",
            "source": "tool_call",
            "stage": "before_call",
            "name": "read_file",
            "call_id": "call-1",
            "provider": "unit",
        }
    )

    payload = _read_config(config_path)
    assert payload["last_runtime_event"]["type"] == "runtime_notice"
    assert payload["runtime_events"][-1]["message"] == "Calling tool: read_file"
    assert logs[-1]["event"] == "runtime_notice"
    assert logs[-1]["tool_name"] == "read_file"
    assert logs[-1]["call_id"] == "call-1"


def test_node_runtime_event_sink_records_tool_lifecycle_and_history(tmp_path):
    sink, config_path, logs, tool_entries = _build_sink(tmp_path)

    sink.handle(
        {
            "type": "TOOL_CALL_START",
            "name": "read_file",
            "call_id": " call-1 ",
            "provider": " unit ",
            "arguments": {"filePath": "README.md"},
            "unexpected": "drop me",
        }
    )
    sink.handle(
        {
            "type": "TOOL_CALL_END",
            "name": "read_file",
            "call_id": " call-1 ",
            "provider": " unit ",
            "status": "completed",
            "duration_ms": 3.4,
            "result_preview": "ok",
            "diagnostics": (" diag ", None),
            "unexpected": "drop me",
        }
    )

    payload = _read_config(config_path)
    assert payload["last_runtime_event"]["type"] == "tool_call_end"
    assert payload["runtime_tool_calls"][0]["arguments"] == {"filePath": "README.md"}
    assert payload["runtime_tool_calls"][0]["status"] == "completed"
    assert [item["event"] for item in logs[-2:]] == ["tool_call_start", "tool_call_end"]
    assert logs[-1]["tool_name"] == "read_file"
    assert tool_entries == [
        {
            "graph_id": "default",
            "node_id": "agent1",
            "event": {
                "type": "tool_call_end",
                "name": "read_file",
                "call_id": "call-1",
                "provider": "unit",
                "status": "completed",
                "duration_ms": 3,
                "arguments": {"filePath": "README.md"},
                "result_preview": "ok",
                "diagnostics": ["diag"],
            },
        }
    ]
    assert "unexpected" not in tool_entries[0]["event"]
