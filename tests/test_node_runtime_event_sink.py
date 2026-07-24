import json
import threading
import time

import pytest

from src.web_backend.delayed_live_activity import DelayedLiveActivityGate
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
    assert logs[-2]["event"] == "server_tool_activity"
    assert logs[-2]["tool_name"] == "web_search"
    assert logs[-1]["event"] == "node_progress_updated"
    assert logs[-1]["source_event"] == "server_tool_activity"
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


def test_node_runtime_event_sink_updates_typed_live_blocks(tmp_path):
    live_blocks = []
    sink, _config_path, _logs, _tool_entries, _runtime_logs = _build_sink(tmp_path)
    sink.tool_live_activity_gate = DelayedLiveActivityGate(delay_seconds=0)
    sink.update_live_activity = lambda graph_id, node_id, block, **kwargs: live_blocks.append(
        {"graph_id": graph_id, "node_id": node_id, "block": block, **kwargs}
    )

    sink.handle(
        {
            "type": "server_tool_activity",
            "call_id": "ws_1",
            "tool_type": "web_search",
            "status": "in_progress",
            "action": {"query": "AgentPark"},
        }
    )
    sink.handle(
        {
            "type": "response_refusal",
            "item_id": "msg_1",
            "text": "I cannot help.",
            "status": "completed",
        }
    )

    assert live_blocks[0]["block"] == {
        "id": "server_tool:ws_1",
        "type": "web_search",
        "label": "Web Searching",
        "status": "in_progress",
        "text": "AgentPark",
        "provider": "",
        "call_id": "ws_1",
        "action": {"query": "AgentPark"},
    }
    assert live_blocks[1]["block"]["type"] == "refusal"
    assert live_blocks[1]["block"]["label"] == "Refusal"
    assert live_blocks[1]["block"]["text"] == "I cannot help."


def test_node_runtime_event_sink_removes_web_search_live_block_at_terminal_status(tmp_path):
    live_blocks = []
    removed_blocks = []
    sink, _config_path, _logs, _tool_entries, _runtime_logs = _build_sink(tmp_path)
    sink.tool_live_activity_gate = DelayedLiveActivityGate(delay_seconds=0)
    sink.update_live_activity = lambda graph_id, node_id, block, **kwargs: live_blocks.append(block)
    sink.remove_live_activity = lambda graph_id, node_id, block_id, **kwargs: removed_blocks.append(block_id)

    base_event = {
        "type": "server_tool_activity",
        "call_id": "ws_1",
        "tool_type": "web_search",
        "action": {"query": "today's news"},
    }
    sink.handle({**base_event, "status": "in_progress"})
    sink.handle({**base_event, "status": "completed"})

    assert live_blocks[0]["label"] == "Web Searching"
    assert live_blocks[0]["text"] == "today's news"
    assert removed_blocks == ["server_tool:ws_1"]


def test_node_runtime_event_sink_hides_server_tool_that_finishes_within_live_threshold(tmp_path):
    live_blocks = []
    removed_blocks = []
    sink, _config_path, _logs, _tool_entries, _runtime_logs = _build_sink(tmp_path)
    sink.tool_live_activity_gate = DelayedLiveActivityGate(delay_seconds=0.04)
    sink.update_live_activity = lambda graph_id, node_id, block, **kwargs: live_blocks.append(block)
    sink.remove_live_activity = lambda graph_id, node_id, block_id, **kwargs: removed_blocks.append(block_id)

    base_event = {
        "type": "server_tool_activity",
        "call_id": "ws-fast",
        "tool_type": "web_search",
        "action": {"query": "AgentPark"},
    }
    sink.handle({**base_event, "status": "in_progress"})
    sink.handle({**base_event, "status": "completed"})
    time.sleep(0.08)

    assert live_blocks == []
    assert removed_blocks == []


def test_node_runtime_event_sink_shows_slow_server_tool_after_live_threshold(tmp_path):
    live_blocks = []
    removed_blocks = []
    live_block_visible = threading.Event()
    sink, _config_path, _logs, _tool_entries, _runtime_logs = _build_sink(tmp_path)
    sink.tool_live_activity_gate = DelayedLiveActivityGate(delay_seconds=0.02)

    def record_live_block(graph_id, node_id, block, **kwargs):
        live_blocks.append(block)
        live_block_visible.set()

    sink.update_live_activity = record_live_block
    sink.remove_live_activity = lambda graph_id, node_id, block_id, **kwargs: removed_blocks.append(block_id)

    base_event = {
        "type": "server_tool_activity",
        "call_id": "ws-slow",
        "tool_type": "web_search",
        "action": {"query": "AgentPark"},
    }
    sink.handle({**base_event, "status": "in_progress"})
    assert live_block_visible.wait(timeout=0.5)
    sink.handle({**base_event, "status": "completed"})

    assert [block["call_id"] for block in live_blocks] == ["ws-slow"]
    assert removed_blocks == ["server_tool:ws-slow"]


@pytest.mark.parametrize(
    ("event_fields", "expected_query"),
    [
        ({"details": {"query": "top-level query"}}, "top-level query"),
        ({"action": {"search_query": "alternate query"}}, "alternate query"),
        ({"action": {"queries": ["first query", "second query"]}}, "first query"),
    ],
)
def test_node_runtime_event_sink_displays_explicit_web_search_query_fields(
    tmp_path,
    event_fields,
    expected_query,
):
    live_blocks = []
    sink, _config_path, _logs, _tool_entries, _runtime_logs = _build_sink(tmp_path)
    sink.tool_live_activity_gate = DelayedLiveActivityGate(delay_seconds=0)
    sink.update_live_activity = lambda graph_id, node_id, block, **kwargs: live_blocks.append(block)

    sink.handle(
        {
            "type": "server_tool_activity",
            "call_id": "ws_1",
            "tool_type": "web_search",
            "status": "in_progress",
            **event_fields,
        }
    )

    assert live_blocks[0]["text"] == expected_query


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


def test_node_runtime_event_sink_moves_oversized_fields_to_artifacts(tmp_path):
    sink, config_path, _logs, _tool_entries, _runtime_logs = _build_sink(tmp_path)
    oversized_message = "x" * (40 * 1024)

    sink.handle(
        {
            "type": "runtime_notice",
            "message": oversized_message,
            "source": "unit",
            "stage": "large_diagnostic",
        }
    )

    record = _read_node_runtime_events(config_path)[-1]
    durable_event = record["runtime_event"]
    artifact = durable_event["message_artifact"]
    assert durable_event["message"].startswith("[oversized runtime event message stored in ")
    assert artifact["type"] == "runtime_event_artifact"
    artifact_path = config_path.parent / artifact["artifact_path"]
    assert json.loads(artifact_path.read_text(encoding="utf-8")) == oversized_message
    assert artifact["json_chars"] == len(json.dumps(oversized_message, ensure_ascii=False, separators=(",", ":")))


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
    assert [item["event"] for item in logs[-3:]] == [
        "tool_call_start",
        "tool_call_end",
        "node_progress_updated",
    ]
    assert logs[-1]["tool_name"] == "read_file"
    assert logs[-1]["source_event"] == "tool_call_end"
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


def test_node_runtime_event_sink_tracks_active_tool_call_as_live_activity(tmp_path):
    live_blocks = []
    removed_blocks = []
    live_block_visible = threading.Event()
    sink, _config_path, _logs, _tool_entries, _runtime_logs = _build_sink(tmp_path)
    sink.tool_live_activity_gate = DelayedLiveActivityGate(delay_seconds=0.02)

    def record_live_block(graph_id, node_id, block, **fields):
        live_blocks.append({"graph_id": graph_id, "node_id": node_id, "block": block, **fields})
        live_block_visible.set()

    sink.update_live_activity = record_live_block
    sink.remove_live_activity = lambda graph_id, node_id, block_id, **fields: removed_blocks.append(
        {"graph_id": graph_id, "node_id": node_id, "block_id": block_id, **fields}
    )

    sink.handle(
        {
            "type": "tool_call_start",
            "name": "execute_console_command",
            "call_id": "call-running",
            "provider": "openai",
            "arguments": {"command": "python -m pytest -q"},
        }
    )
    assert live_block_visible.wait(timeout=0.5)
    sink.handle(
        {
            "type": "tool_call_end",
            "name": "execute_console_command",
            "call_id": "call-running",
            "provider": "openai",
            "status": "stopped",
            "result_preview": "UserStoppedThisCall",
        }
    )

    assert live_blocks[0]["block"] == {
        "id": "tool_call:call-running",
        "type": "tool_call",
        "label": "execute_console_command",
        "status": "running",
        "provider": "openai",
        "call_id": "call-running",
        "arguments": {"command": "python -m pytest -q"},
    }
    assert removed_blocks[0]["block_id"] == "tool_call:call-running"


def test_node_runtime_event_sink_hides_tool_calls_that_finish_within_live_threshold(tmp_path):
    live_blocks = []
    removed_blocks = []
    sink, _config_path, _logs, _tool_entries, _runtime_logs = _build_sink(tmp_path)
    sink.tool_live_activity_gate = DelayedLiveActivityGate(delay_seconds=0.04)
    sink.update_live_activity = lambda graph_id, node_id, block, **fields: live_blocks.append(block)
    sink.remove_live_activity = lambda graph_id, node_id, block_id, **fields: removed_blocks.append(block_id)

    sink.handle({"type": "tool_call_start", "name": "read_file", "call_id": "call-fast"})
    sink.handle(
        {
            "type": "tool_call_end",
            "name": "read_file",
            "call_id": "call-fast",
            "status": "completed",
            "duration_ms": 3,
        }
    )
    time.sleep(0.08)

    assert live_blocks == []
    assert removed_blocks == []


def test_node_runtime_event_sink_delays_concurrent_tool_calls_independently(tmp_path):
    live_blocks = []
    removed_blocks = []
    slow_call_visible = threading.Event()
    sink, _config_path, _logs, _tool_entries, _runtime_logs = _build_sink(tmp_path)
    sink.tool_live_activity_gate = DelayedLiveActivityGate(delay_seconds=0.03)

    def record_live_block(graph_id, node_id, block, **fields):
        live_blocks.append(block)
        if block["call_id"] == "call-slow":
            slow_call_visible.set()

    sink.update_live_activity = record_live_block
    sink.remove_live_activity = lambda graph_id, node_id, block_id, **fields: removed_blocks.append(block_id)

    sink.handle({"type": "tool_call_start", "name": "read_file", "call_id": "call-fast"})
    sink.handle({"type": "tool_call_start", "name": "execute_console_command", "call_id": "call-slow"})
    sink.handle({"type": "tool_call_end", "name": "read_file", "call_id": "call-fast", "status": "completed"})

    assert slow_call_visible.wait(timeout=0.5)
    sink.handle(
        {
            "type": "tool_call_end",
            "name": "execute_console_command",
            "call_id": "call-slow",
            "status": "completed",
        }
    )

    assert [block["call_id"] for block in live_blocks] == ["call-slow"]
    assert removed_blocks == ["tool_call:call-slow"]


def test_node_runtime_event_sink_close_cancels_pending_tool_live_activity(tmp_path):
    live_blocks = []
    sink, _config_path, _logs, _tool_entries, _runtime_logs = _build_sink(tmp_path)
    sink.tool_live_activity_gate = DelayedLiveActivityGate(delay_seconds=0.04)
    sink.update_live_activity = lambda graph_id, node_id, block, **fields: live_blocks.append(block)
    sink.remove_live_activity = lambda graph_id, node_id, block_id, **fields: None

    sink.handle({"type": "tool_call_start", "name": "read_file", "call_id": "call-pending"})
    sink.close()
    time.sleep(0.08)

    assert live_blocks == []


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
    assert not any(item["event"] == "node_progress_updated" for item in logs)
    assert any(item["event_type"] == "runtime_notice" for item in live_events)
    assert live_events[-1]["event_type"] == "tool_call_end"
    assert "NodeMemoryPersistenceError" in live_events[-1]["event"]["memory_persistence_warning"]
