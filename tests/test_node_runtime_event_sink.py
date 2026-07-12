import json

import pytest

from src.web_backend.node_memory_store import NodeMemoryPersistenceError
from src.web_backend.node_memory_store import NodeMemoryPersistenceFailure
from src.web_backend.node_runtime_event_sink import NodeRuntimeEventSink
from src.web_backend.state_store import _read_json_dict, _write_json_dict


def _read_config(path):
    return _read_json_dict(str(path))


def _build_sink(tmp_path):
    config_path = tmp_path / "config.json"
    _write_json_dict(str(config_path), {"node_id": "agent1"})
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


def _read_node_runtime_events(config_path):
    path = config_path.with_name("runtime_events.jsonl")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_node_runtime_event_sink_updates_stream_text_and_done_log(tmp_path):
    sink, config_path, logs, tool_entries, runtime_logs = _build_sink(tmp_path)

    sink.handle({"type": "node_message_delta", "delta": " world", "text": "hello world"})
    assert sink.stream_output_chars == 6
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
        sink.handle({"type": "delta", "text": "unsupported"})


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


def test_node_runtime_event_sink_publishes_server_tool_activity(tmp_path):
    published = []
    sink, config_path, logs, tool_entries, runtime_logs = _build_sink(tmp_path)
    sink.publish_live_event = lambda graph_id, node_id, event_type, event, **kwargs: published.append(
        {"graph_id": graph_id, "node_id": node_id, "event_type": event_type, "event": event, **kwargs}
    )

    sink.handle(
        {
            "type": "server_tool_activity",
            "call_id": "ws_1",
            "tool_type": "web_search",
            "status": "completed",
            "provider": "openai",
            "sources": [{"url": "https://example.com"}],
        }
    )

    payload = _read_config(config_path)
    assert payload["last_runtime_event"]["type"] == "server_tool_activity"
    assert published[-1]["event_type"] == "server_tool_activity"
    assert logs[-1]["tool_name"] == "web_search"
    assert runtime_logs[-1]["event"] == "server_tool_activity"
    assert tool_entries == [
        {
            "graph_id": "default",
            "node_id": "agent1",
            "event": {
                "call_id": "ws_1",
                "name": "web_search",
                "provider": "openai",
                "status": "completed",
                "result_preview": "1 source",
                "sources": [{"url": "https://example.com"}],
            },
        }
    ]


def test_node_runtime_event_sink_persists_server_tool_only_at_terminal_status(tmp_path):
    sink, _config_path, _logs, tool_entries, _runtime_logs = _build_sink(tmp_path)
    base_event = {
        "type": "server_tool_activity",
        "call_id": "ws_1",
        "tool_type": "web_search",
        "provider": "openai",
        "action": {"query": "AgentPark"},
    }

    sink.handle({**base_event, "status": "in_progress"})
    assert tool_entries == []

    sink.handle({**base_event, "status": "completed"})
    sink.handle({**base_event, "status": "completed"})

    assert len(tool_entries) == 1
    assert tool_entries[0]["event"] == {
        "call_id": "ws_1",
        "name": "web_search",
        "provider": "openai",
        "status": "completed",
        "arguments": {"query": "AgentPark"},
    }


def test_node_runtime_event_sink_emits_runtime_notice_and_net_error_events(tmp_path):
    emitted = []
    sink, _config_path, _logs, _tool_entries, _runtime_logs = _build_sink(tmp_path)
    sink.emit_runtime_event = lambda **kwargs: emitted.append(kwargs)

    sink.handle(
        {
            "type": "runtime_notice",
            "message": "Provider timeout; retrying connection",
            "source": "provider",
            "stage": "request_retry",
            "provider": "unit",
        }
    )

    assert [item["event"] for item in emitted] == ["RuntimeNotice", "NetError"]
    assert emitted[0]["graph_id"] == "default"
    assert emitted[0]["node_id"] == "agent1"


def test_node_runtime_event_sink_persists_provider_request_summary_to_node_log(tmp_path):
    sink, config_path, _logs, _tool_entries, _runtime_logs = _build_sink(tmp_path)
    summary = {
        "request_index": 2,
        "continuation_mode": "explicit_context",
        "responses_mode": "item_level",
        "input_item_count": 7,
        "approx_input_chars": 45678,
        "approx_input_tokens": 11111,
        "largest_input_items": [{"index": 4, "type": "function_call_output", "chars": 28784}],
        "tools_included": ["execute_console_command", "rg_list_files"],
        "tools_included_count": 2,
        "stream": True,
    }

    sink.handle(
        {
            "type": "runtime_notice",
            "message": json.dumps(summary, ensure_ascii=False),
            "source": "openai",
            "stage": "provider_request_summary",
            "provider": "krill_gpt55",
        }
    )

    records = _read_node_runtime_events(config_path)
    assert records[-1]["event"] == "runtime_notice"
    assert records[-1]["runtime_event"]["stage"] == "provider_request_summary"
    assert records[-1]["provider_request_summary"]["request_index"] == 2
    assert records[-1]["provider_request_summary"]["approx_input_tokens"] == 11111
    assert records[-1]["provider_request_summary"]["largest_input_items"][0]["chars"] == 28784


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
    runtime_event_records = _read_node_runtime_events(config_path)
    assert [item["event"] for item in runtime_event_records[-2:]] == ["tool_call_start", "tool_call_end"]
    assert runtime_event_records[-1]["runtime_event"]["result_tail_preview"] == "ok"


def test_node_runtime_event_sink_emits_tool_failure_event(tmp_path):
    emitted = []
    sink, _config_path, _logs, _tool_entries, _runtime_logs = _build_sink(tmp_path)
    sink.emit_runtime_event = lambda **kwargs: emitted.append(kwargs)

    sink.handle({"type": "tool_call_start", "name": "read_file", "call_id": "call-1"})
    sink.handle(
        {
            "type": "tool_call_end",
            "name": "read_file",
            "call_id": "call-1",
            "status": "error",
            "error": "file missing",
        }
    )

    assert [item["event"] for item in emitted] == ["ToolFailure"]
    assert emitted[0]["payload"].get("tool_name") == "read_file" or emitted[0]["payload"].get("name") == "read_file"


def test_node_runtime_event_sink_keeps_tool_end_nonfatal_when_history_persist_fails(tmp_path):
    config_path = tmp_path / "config.json"
    _write_json_dict(str(config_path), {"node_id": "agent1"})
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
