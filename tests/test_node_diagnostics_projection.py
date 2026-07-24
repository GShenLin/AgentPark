import json

import pytest

from src.web_backend.node_config_store import NodeConfigStore
from src.web_backend.node_diagnostics_projection import (
    DIAGNOSTICS_PROJECTION_FILENAME,
    NodeDiagnosticsProjectionError,
    NodeDiagnosticsProjectionStore,
)
from src.web_backend.runtime_state_memory_store import runtime_state_memory_store


def _tool_start(call_id: str) -> dict:
    return {
        "type": "tool_call_start",
        "name": "read_file",
        "call_id": call_id,
        "arguments": {"path": "README.md"},
    }


def _run_summary() -> dict:
    return {
        "type": "runtime_notice",
        "source": "node_runtime",
        "stage": "node_run_summary",
        "message": '{"status":"completed","duration_ms":10}',
    }


def test_runtime_event_persists_projection_at_run_boundary(tmp_path):
    config_path = str(tmp_path / "config.json")
    config_path_obj = tmp_path / "config.json"
    config_path_obj.write_text('{"type_id":"agent_node"}', encoding="utf-8")

    store = NodeConfigStore()
    store.set_runtime_event(config_path, _tool_start("call-1"))

    projection_path = tmp_path / DIAGNOSTICS_PROJECTION_FILENAME
    assert not projection_path.exists()

    store.set_runtime_event(config_path, _run_summary())
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    assert projection["last_runtime_event"]["stage"] == "node_run_summary"
    assert projection["runtime_tool_calls"][0]["status"] == "running"
    assert "state" not in projection
    assert "last_message" not in projection


def test_runtime_event_hydrates_durable_history_after_process_memory_reset(tmp_path):
    config_path = str(tmp_path / "config.json")
    (tmp_path / "config.json").write_text('{"type_id":"agent_node"}', encoding="utf-8")
    store = NodeConfigStore()
    store.set_runtime_event(config_path, _tool_start("call-1"))
    store.set_runtime_event(config_path, _run_summary())

    runtime_state_memory_store.clear(config_path)
    store.set_runtime_event(config_path, _tool_start("call-2"))
    store.set_runtime_event(config_path, _run_summary())

    projection = NodeDiagnosticsProjectionStore().read(config_path)
    assert [item["call_id"] for item in projection["runtime_tool_calls"]] == ["call-1", "call-2"]


def test_runtime_event_history_reset_rewrites_projection(tmp_path):
    config_path = str(tmp_path / "config.json")
    (tmp_path / "config.json").write_text('{"type_id":"agent_node"}', encoding="utf-8")
    store = NodeConfigStore()
    store.set_runtime_event(config_path, _tool_start("call-1"))

    store.set_runtime_event(config_path, None, reset_history=True)

    assert NodeDiagnosticsProjectionStore().read(config_path) == {}


def test_corrupt_diagnostics_projection_is_not_silently_ignored(tmp_path):
    config_path = str(tmp_path / "config.json")
    (tmp_path / DIAGNOSTICS_PROJECTION_FILENAME).write_text("{not-json", encoding="utf-8")

    with pytest.raises(NodeDiagnosticsProjectionError, match="failed to read"):
        NodeDiagnosticsProjectionStore().read(config_path)


def test_diagnostics_projection_can_read_only_board_fields(tmp_path):
    config_path = str(tmp_path / "config.json")
    store = NodeDiagnosticsProjectionStore()
    store.write(
        config_path,
        {
            "runtime_tool_calls": [{"call_id": "call-1"}],
            "completed_requests": [{"request_index": 1, "payload": "x" * 10_000}],
        },
    )

    selected = store.read(config_path, fields={"runtime_tool_calls"})

    assert selected == {"runtime_tool_calls": [{"call_id": "call-1"}]}


def test_runtime_event_update_does_not_copy_unrelated_large_runtime_fields(monkeypatch, tmp_path):
    config_path = str(tmp_path / "config.json")
    (tmp_path / "config.json").write_text('{"type_id":"agent_node"}', encoding="utf-8")
    large_message = "x" * 500_000
    runtime_state_memory_store.replace(
        config_path,
        {
            "completed_requests": [{"request_id": "request-1", "message": large_message}],
            "last_completed_request": {"request_id": "request-1", "message": large_message},
        },
    )
    copied_completed_requests = False
    original_deepcopy = __import__("copy").deepcopy

    def track_deepcopy(value, *args, **kwargs):
        nonlocal copied_completed_requests
        if isinstance(value, list) and value and isinstance(value[0], dict) and value[0].get("request_id") == "request-1":
            copied_completed_requests = True
        return original_deepcopy(value, *args, **kwargs)

    monkeypatch.setattr("src.web_backend.runtime_state_memory_store.copy.deepcopy", track_deepcopy)
    NodeConfigStore().set_runtime_event(config_path, _tool_start("call-1"))

    assert copied_completed_requests is False
    snapshot = runtime_state_memory_store.snapshot_fields(
        config_path,
        {"runtime_tool_calls", "completed_requests"},
        include_defaults=False,
    )
    assert snapshot["runtime_tool_calls"][0]["call_id"] == "call-1"
    assert snapshot["completed_requests"][0]["message"] == large_message


def test_stop_check_does_not_copy_unrelated_runtime_state(monkeypatch, tmp_path):
    config_path = str(tmp_path / "config.json")
    runtime_state_memory_store.replace(
        config_path,
        {
            "_stop_requested": True,
            "completed_requests": [{"request_id": "request-1", "message": "x" * 500_000}],
        },
    )

    def fail_full_snapshot(*_args, **_kwargs):
        raise AssertionError("stop checks must not materialize the full runtime state")

    monkeypatch.setattr(runtime_state_memory_store, "snapshot", fail_full_snapshot)

    assert NodeConfigStore().is_stop_requested(config_path) is True
