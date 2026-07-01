import json

import pytest

from src.web_backend.node_memory_store import NodeMemoryPersistenceError
from src.web_backend.node_memory_store import NodeMemoryPersistenceFailure
from src.web_backend.node_runtime_event_sink import NodeRuntimeEventSink
from src.web_backend.node_config_service import node_runtime_state_path


def _read_config(path):
    with open(node_runtime_state_path(str(path)), "r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_sink(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"node_id": "agent1"}, ensure_ascii=False), encoding="utf-8")
    logs = []
    runtime_logs = []
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
        append_runtime_log=lambda graph_id, event, **fields: runtime_logs.append(
            {"graph_id": graph_id, "event": event, **fields}
        ),
    )
    return sink, config_path, logs, tool_entries, runtime_logs


def test_node_runtime_event_sink_updates_stream_text_and_done_log(tmp_path):
    sink, config_path, logs, tool_entries, runtime_logs = _build_sink(tmp_path)

    sink.handle({"type": "node_message_delta", "text": "hello world"})
    sink.handle({"type": "node_message_done", "text": "hello world!"})

    payload = _read_config(config_path)
    assert payload["last_message"] == "hello world!"
    assert sink.stream_last_text == "hello world!"
    assert logs[-1]["event"] == "node_message_done"
    assert logs[-1]["output_preview"] == "hello world!"
    assert tool_entries == []
    assert [item["event"] for item in runtime_logs] == ["node_message_done"]
    assert runtime_logs[-1]["message"] == "hello world!"
    assert runtime_logs[-1]["node_instance_id"] == "agent1"


def test_node_runtime_event_sink_rejects_unknown_event_type(tmp_path):
    sink, _config_path, _logs, _tool_entries, _runtime_logs = _build_sink(tmp_path)

    with pytest.raises(ValueError, match="unsupported node runtime event type"):
        sink.handle({"type": "delta", "text": "legacy"})


def test_node_runtime_event_sink_records_runtime_notice(tmp_path):
    sink, config_path, logs, _tool_entries, runtime_logs = _build_sink(tmp_path)

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
    assert runtime_logs[-1]["event"] == "runtime_notice"
    assert runtime_logs[-1]["message"] == "Calling tool: read_file"
    assert runtime_logs[-1]["tool_name"] == "read_file"


def test_node_runtime_event_sink_records_tool_lifecycle_and_history(tmp_path):
    sink, config_path, logs, tool_entries, runtime_logs = _build_sink(tmp_path)

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
            "result_chars": 2,
            "result_preview_truncated": False,
            "result_tail_preview": "ok",
            "result_tail_preview_truncated": False,
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
    assert [item["event"] for item in runtime_logs] == ["tool_call_start", "tool_call_end"]
    assert runtime_logs[-1]["arguments"] == {"filePath": "README.md"}
    assert runtime_logs[-1]["result_preview"] == "ok"
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
                "result_chars": 2,
                "result_preview_truncated": False,
                "result_tail_preview": "ok",
                "result_tail_preview_truncated": False,
                "diagnostics": ["diag"],
            },
        }
    ]
    assert "unexpected" not in tool_entries[0]["event"]


def test_node_runtime_event_sink_keeps_tool_end_nonfatal_when_history_persist_fails(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"node_id": "agent1"}, ensure_ascii=False), encoding="utf-8")
    logs = []
    live_events = []

    def fail_append(_graph_id, _node_id, _event):
        raise NodeMemoryPersistenceError(
            [
                NodeMemoryPersistenceFailure(
                    target="messages",
                    path=str(tmp_path / "messages.jsonl"),
                    error="PermissionError: locked",
                )
            ]
        )

    sink = NodeRuntimeEventSink(
        graph_id="default",
        node_id="agent1",
        node_type_id="agent_node",
        config_path=str(config_path),
        trace_id="trace-1",
        depth=2,
        stream_last_text="",
        log_graph_event=lambda graph_id, event, **fields: logs.append(
            {"graph_id": graph_id, "event": event, **fields}
        ),
        append_tool_call_entry=fail_append,
        publish_live_event=lambda graph_id, node_id, event_type, event, **fields: live_events.append(
            {"graph_id": graph_id, "node_id": node_id, "event_type": event_type, "event": event, **fields}
        ),
    )

    sink.handle({"type": "tool_call_start", "name": "read_file", "call_id": "call-1"})
    feedback = sink.handle({"type": "tool_call_end", "name": "read_file", "call_id": "call-1", "status": "completed"})

    payload = _read_config(config_path)
    assert "NodeMemoryPersistenceError" in feedback["memory_persistence_warning"]
    assert payload["last_runtime_event"]["type"] == "tool_call_end"
    assert "NodeMemoryPersistenceError" in payload["last_runtime_event"]["memory_persistence_warning"]
    assert payload["runtime_tool_calls"][0]["status"] == "completed"
    assert "NodeMemoryPersistenceError" in payload["runtime_tool_calls"][0]["memory_persistence_warning"]
    failure_log = next(item for item in logs if item["event"] == "node_memory_persist_failed")
    assert failure_log["target"] == "tool_history"
    assert failure_log["failures"][0]["target"] == "messages"
    assert any(item["event_type"] == "runtime_notice" for item in live_events)
    assert live_events[-1]["event_type"] == "tool_call_end"
    assert "NodeMemoryPersistenceError" in live_events[-1]["event"]["memory_persistence_warning"]
