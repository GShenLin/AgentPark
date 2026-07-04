from src.web_backend.node_live_output import NodeLiveOutputStore
from src.web_backend.node_runtime_event_sink import NodeRuntimeEventSink
from src.web_backend.state_store import _read_json_dict, _write_json_dict


def test_stream_delta_updates_live_output_and_done_persists_last_message(tmp_path):
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
        clear_live_output=live_store.clear,
    )

    sink.handle({"type": "node_message_delta", "delta": "hello", "text": "hello"})

    payload = _read_json_dict(config_path)
    assert payload["last_message"] == "input"
    assert live_store.get("g1", "n1")["text"] == "hello"

    sink.handle({"type": "node_message_done", "text": "hello"})

    payload = _read_json_dict(config_path)
    assert payload["last_message"] == "hello"
    cleared = live_store.get("g1", "n1")
    assert cleared.get("text", "") == ""
    assert int(cleared.get("version") or 0) > 0
