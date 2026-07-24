from src.web_backend.node_live_output import NodeLiveOutputStore, build_live_output_payload, live_output_requires_snapshot
from src.web_backend.node_runtime_event_sink import NodeRuntimeEventSink
from src.web_backend.state_store import _read_json_dict, _write_json_dict


def test_stream_delta_updates_live_output_and_done_publishes_completion_event(tmp_path):
    config_path = str(tmp_path / "config.json")
    _write_json_dict(config_path, {"node_id": "n1", "last_message": "input"})
    live_store = NodeLiveOutputStore()
    logged = []

    sink = NodeRuntimeEventSink(
        graph_id="g1",
        node_id="n1",
        node_type_id="agent_node",
        config_path=config_path,
        trace_id="trace-1",
        depth=0,
        stream_last_text="input",
        log_graph_event=lambda *args, **kwargs: logged.append((args, kwargs)),
        append_tool_call_entry=lambda *_args, **_kwargs: None,
        update_live_output=live_store.update,
        publish_completion_event=live_store.publish_completion_event,
    )

    sink.handle({"type": "node_message_delta", "delta": "hello", "text": "hello"})

    payload = _read_json_dict(config_path)
    assert payload["last_message"] == "input"
    assert live_store.get("g1", "n1")["text"] == "hello"

    sink.handle({"type": "node_message_done", "text": "hello"})

    payload = _read_json_dict(config_path)
    assert payload["last_message"] == "hello"
    live_after_done = live_store.get("g1", "n1")
    assert live_after_done["text"] == ""
    assert live_after_done["event_type"] == "node_message_done"
    assert live_after_done["event"]["text"] == "hello"
    assert int(live_after_done.get("version") or 0) > 0


def test_live_output_store_upserts_removes_and_clears_activity_blocks():
    live_store = NodeLiveOutputStore()

    live_store.update_activity(
        "g1",
        "n1",
        {"id": "server_tool:ws_1", "type": "web_search", "label": "WebSearch", "status": "in_progress"},
    )
    current = live_store.get("g1", "n1")
    assert current["activity_blocks"] == [
        {"id": "server_tool:ws_1", "type": "web_search", "label": "WebSearch", "status": "in_progress"}
    ]

    live_store.remove_activity("g1", "n1", "server_tool:ws_1")
    assert live_store.get("g1", "n1")["activity_blocks"] == []


def test_live_output_store_emits_delta_and_requests_snapshot_on_mismatch():
    live_store = NodeLiveOutputStore()

    live_store.update("g1", "n1", "hello", delta="hello")
    current = live_store.get("g1", "n1")
    assert current["live_delta"] == "hello"
    assert current["snapshot_required"] is False
    assert current["activity_blocks_changed"] is False

    live_store.update("g1", "n1", "replacement", delta=" world")
    current = live_store.get("g1", "n1")
    assert current["live_delta"] == ""
    assert current["snapshot_required"] is True


def test_live_output_delivery_requires_snapshot_when_consumer_skips_a_version():
    live_store = NodeLiveOutputStore()

    live_store.update("g1", "n1", "你", delta="你")
    first = live_store.get("g1", "n1")
    assert live_output_requires_snapshot(first, 0) is False

    live_store.update("g1", "n1", "你好", delta="好")
    latest = live_store.wait_for_change("g1", "n1", 0, timeout=0.1)

    assert latest["version"] == 2
    assert latest["live_delta"] == "好"
    assert latest["text"] == "你好"
    assert latest["snapshot_required"] is False
    assert live_output_requires_snapshot(latest, 0) is True


def test_live_output_payload_sends_snapshot_after_skipped_version():
    live_store = NodeLiveOutputStore()
    live_store.update("g1", "n1", "你", delta="你")
    initial_payload = build_live_output_payload("g1", "n1", live_store.get("g1", "n1"), snapshot=True)
    live_store.update("g1", "n1", "你好", delta="好")
    live_store.update("g1", "n1", "你好！", delta="！")
    recovered_payload = build_live_output_payload(
        "g1",
        "n1",
        live_store.get("g1", "n1"),
        last_delivered_version=1,
    )

    assert initial_payload["stream_type"] == "snapshot"
    assert initial_payload["live_message"] == "你"
    assert recovered_payload["version"] == 3
    assert recovered_payload["stream_type"] == "snapshot"
    assert recovered_payload["live_message"] == "你好！"
    assert recovered_payload["live_delta"] == ""


def test_live_output_store_bounds_activity_history_and_event_fields():
    live_store = NodeLiveOutputStore()

    for index in range(80):
        live_store.update_activity(
            "g1",
            "n1",
            {
                "id": f"tool:{index}",
                "type": "tool",
                "text": "x" * 5000,
            },
            event={"type": "tool_activity", "details": "y" * 5000},
        )

    current = live_store.get("g1", "n1")
    assert len(current["activity_blocks"]) == 64
    assert current["activity_blocks"][0]["id"] == "tool:16"
    assert len(current["activity_blocks"][-1]["text"]) <= 4097
    assert len(current["event"]["details"]) <= 4097
    assert current["activity_blocks_changed"] is True


def test_live_output_store_preserves_activity_fields_omitted_by_later_status_event():
    live_store = NodeLiveOutputStore()

    live_store.update_activity(
        "g1",
        "n1",
        {
            "id": "server_tool:ws_1",
            "type": "web_search",
            "label": "Web Searching",
            "status": "in_progress",
            "text": "AgentPark SSE",
            "action": {"query": "AgentPark SSE"},
        },
    )
    live_store.update_activity(
        "g1",
        "n1",
        {
            "id": "server_tool:ws_1",
            "type": "web_search",
            "label": "Web Searching",
            "status": "in_progress",
            "provider": "openai",
        },
    )

    assert live_store.get("g1", "n1")["activity_blocks"] == [
        {
            "id": "server_tool:ws_1",
            "type": "web_search",
            "label": "Web Searching",
            "status": "in_progress",
            "text": "AgentPark SSE",
            "action": {"query": "AgentPark SSE"},
            "provider": "openai",
        }
    ]

    live_store.update_activity(
        "g1",
        "n1",
        {"id": "server_tool:fs_1", "type": "file_search", "label": "FileSearch", "status": "completed"},
    )

    live_store.publish_completion_event("g1", "n1", "node_message_done", {"type": "node_message_done"})
    assert live_store.get("g1", "n1")["activity_blocks"] == []
