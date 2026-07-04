import json
import threading
import time

import src.web_backend.graph_timer_scheduler as timer_module
from src.message_protocol import envelope_text
from src.web_backend.core import BackendCore
from src.web_backend.state_store import _read_json_dict, _write_json_dict


def _read_runtime_state(config_path):
    return _read_json_dict(str(config_path))


def test_clock_scan_ignores_irrelevant_runtime_state(monkeypatch, tmp_path):
    core = BackendCore()
    graph_runtime = core.graph_runtime

    monkeypatch.setattr(timer_module.runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(graph_runtime, "_ensure_graph_runner", lambda _graph_id: None)
    monkeypatch.setattr(graph_runtime, "_wake_graph_runner", lambda _graph_id: None)

    graph_id = "clock_graph_with_agent_history"
    graph_dir = tmp_path / "memories" / graph_id
    agent_dir = graph_dir / "agent_node_1"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "config.json").write_text(
        json.dumps({"node_id": "agent_node_1", "type_id": "agent_node"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (agent_dir / "runtime_state.json").write_text("{not valid json", encoding="utf-8")

    node_id = "clock_node_due"
    node_dir = graph_dir / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    config_path = node_dir / "config.json"
    config = {
        "node_id": node_id,
        "type_id": "clock_node",
        "state": "working",
        "IntervalDays": "0",
        "IntervalHours": "0",
        "IntervalMinutes": "0",
        "IntervalSeconds": "5",
        "IsLoop": "true",
        "LoopCount": "0",
        "OutputText": "clock-fire",
        "_clock_running": True,
        "_clock_next_fire_at": time.time() - 0.1,
        "_clock_remaining_seconds": 0,
        "_clock_trigger_count": 0,
    }
    _write_json_dict(str(config_path), config)

    assert graph_runtime._scan_and_emit_scheduled_nodes_once() == 1

    updated_runtime = _read_runtime_state(config_path)
    pending = updated_runtime.get("pending")
    assert isinstance(pending, list)
    assert len(pending) == 1
    assert envelope_text(pending[0].get("payload")) == "clock-fire"


def test_registered_clock_schedule_fires_without_scan(monkeypatch, tmp_path):
    core = BackendCore()
    graph_runtime = core.graph_runtime

    monkeypatch.setattr(timer_module.runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(graph_runtime, "_ensure_graph_runner", lambda _graph_id: None)
    monkeypatch.setattr(graph_runtime, "_wake_graph_runner", lambda _graph_id: None)

    graph_id = "registered_clock_graph"
    node_id = "registered_clock_node"
    node_dir = tmp_path / "memories" / graph_id / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    config_path = node_dir / "config.json"
    config = {
        "node_id": node_id,
        "type_id": "clock_node",
        "state": "working",
        "IntervalDays": "0",
        "IntervalHours": "0",
        "IntervalMinutes": "0",
        "IntervalSeconds": "1",
        "IsLoop": "false",
        "LoopCount": "0",
        "OutputText": "registered-clock-fire",
        "_clock_running": True,
        "_clock_next_fire_at": time.time() + 0.05,
        "_clock_remaining_seconds": 1,
        "_clock_trigger_count": 0,
    }
    _write_json_dict(str(config_path), config)

    assert graph_runtime._register_all_scheduled_nodes() == 1
    due = graph_runtime._scheduled_node_registry().wait_for_due(threading.Event())
    assert len(due) == 1
    assert due[0].graph_id == graph_id
    assert due[0].node_id == node_id

    assert graph_runtime._handle_registered_schedule(due[0]) == 1

    runtime_updated = _read_runtime_state(config_path)
    pending = runtime_updated.get("pending")
    assert isinstance(pending, list)
    assert envelope_text(pending[0].get("payload")) == "registered-clock-fire"
    assert runtime_updated.get("state") == "idle"


def test_schedule_index_restores_registry_without_config_scan(monkeypatch, tmp_path):
    core = BackendCore()
    graph_runtime = core.graph_runtime

    monkeypatch.setattr(timer_module.runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    graph_id = "indexed_schedule_graph"
    node_id = "indexed_clock_node"
    node_dir = tmp_path / "memories" / graph_id / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    config_path = node_dir / "config.json"
    config = {
        "node_id": node_id,
        "type_id": "clock_node",
        "state": "working",
        "IntervalDays": "0",
        "IntervalHours": "1",
        "IntervalMinutes": "0",
        "IntervalSeconds": "0",
        "IsLoop": "true",
        "LoopCount": "0",
        "OutputText": "clock-fire",
        "_clock_running": True,
        "_clock_next_fire_at": time.time() + 3600,
        "_clock_remaining_seconds": 3600,
        "_clock_trigger_count": 0,
    }
    _write_json_dict(str(config_path), config)

    assert graph_runtime._register_all_scheduled_nodes(force_rebuild=True) == 1

    core2 = BackendCore()
    graph_runtime2 = core2.graph_runtime
    monkeypatch.setattr(graph_runtime2._scheduled_node_config_cache(), "iter_scheduled_configs", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected config scan")))

    assert graph_runtime2._register_all_scheduled_nodes() == 0
    entries = graph_runtime2._scheduled_node_registry().snapshot()
    assert entries == []
