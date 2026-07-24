from pathlib import Path

from src.web_backend.core import BackendCore
from src.web_backend.node_config_service import node_config_service
from src.web_backend.runtime_state_memory_store import runtime_state_memory_store


def _patch_workspace(monkeypatch, tmp_path):
    from src.web_backend import profile_storage, runtime_paths

    monkeypatch.setattr(runtime_paths, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(profile_storage, "get_workspace_root", lambda: str(tmp_path))


def _write_graph_node(tmp_path, graph_id: str, node_id: str) -> str:
    graph_dir = tmp_path / "memories" / graph_id
    graph_dir.mkdir(parents=True, exist_ok=True)
    (graph_dir / "config.json").write_text(
        f'{{"id":"{graph_id}","name":"{graph_id}","output_routes":{{}}}}',
        encoding="utf-8",
    )
    node_dir = graph_dir / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    config_path = str(node_dir / "config.json")
    node_config_service.create_or_replace(
        config_path,
        {
            "node_id": node_id,
            "graph_id": graph_id,
            "type_id": "agent_node",
            "name": node_id,
            "state": "idle",
        },
    )
    return config_path


def test_graph_event_contains_node_runtime_delta(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    config_path = _write_graph_node(tmp_path, "test", "Agent")
    core = BackendCore()
    runtime_state_memory_store.update(
        config_path,
        lambda state: state.update({"state": "working", "last_run_at": "2026-07-22 12:00:00.000000"}),
    )

    core.graph_runtime._log_graph_event(
        "test",
        "tool_call_start",
        node_instance_id="Agent",
        tool_name="read_file",
    )

    event = core.graph_events.get("test")
    assert event["event"] == "tool_call_start"
    assert event["node_runtime"] == {
        "node_id": "Agent",
        "state": "working",
        "pending_count": 0,
        "last_run_at": "2026-07-22 12:00:00.000000",
    }


def test_graph_event_runtime_delta_reports_pending_count_without_exposing_queue(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    config_path = _write_graph_node(tmp_path, "test", "Agent")
    core = BackendCore()
    runtime_state_memory_store.update(
        config_path,
        lambda state: state.update(
            {
                "state": "working",
                "pending": [{"payload": "next"}],
            }
        ),
    )

    core.graph_runtime._log_graph_event("test", "node_pending_enqueued", node_instance_id="Agent")

    runtime_delta = core.graph_events.get("test")["node_runtime"]
    assert runtime_delta["pending_count"] == 1
    assert "pending" not in runtime_delta


def test_live_output_is_multiplexed_into_global_graph_event_store(monkeypatch, tmp_path):
    _patch_workspace(monkeypatch, tmp_path)
    _write_graph_node(tmp_path, "test", "Agent")
    core = BackendCore()

    core.node_live_outputs.update("test", "Agent", "hello", delta="hello")

    event = core.graph_events.get("test")
    assert event["event"] == "node_live"
    assert event["node_id"] == "Agent"
    assert event["live"]["stream_type"] == "snapshot"
    assert event["live"]["live_message"] == "hello"
    assert event["live"]["version"] == 1


def test_webui_owns_exactly_one_event_source_and_legacy_streams_are_retired():
    workspace = Path(__file__).resolve().parents[1]
    webui_sources = list((workspace / "webui" / "src").rglob("*.ts")) + list(
        (workspace / "webui" / "src").rglob("*.vue")
    )
    event_source_owners = []
    combined = ""
    for source_path in webui_sources:
        source = source_path.read_text(encoding="utf-8")
        combined += source
        if "new EventSource(" in source:
            event_source_owners.append(source_path.relative_to(workspace).as_posix())

    routes = (workspace / "src" / "web_backend" / "route_registry.py").read_text(encoding="utf-8")

    assert event_source_owners == ["webui/src/composables/useAppEventStream.ts"]
    assert "graphEventsStreamUrl" not in combined
    assert "nodeInstanceLiveStreamUrl" not in combined
    assert routes.count("/api/graphs/{graph_id}/events/stream") == 1
    assert routes.count("/api/nodes/instances/{node_id}/live/stream") == 1
    assert routes.count("retire_legacy_event_stream") == 2
    assert routes.count("/api/app/events/stream") == 1


def test_config_query_uses_compact_projection_instead_of_runtime_event_log_scan():
    workspace = Path(__file__).resolve().parents[1]
    source = (workspace / "src" / "web_backend" / "node_instance_config_query.py").read_text(encoding="utf-8")

    assert "node_diagnostics_projection_store.read" in source
    assert "load_node_runtime_projection" not in source
    assert "runtime_events.jsonl" not in source
    assert "diagnostics_fields=BOARD_RUNTIME_FIELDS" in source
