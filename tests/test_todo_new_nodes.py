import json
import time
from datetime import datetime

from src.message_protocol import envelope_text


def test_basic_trigger_node_outputs_config_text():
    from nodes.basic_trigger_node import Node

    node = Node()
    cfg = {}
    node.on_create(cfg, None)

    assert cfg.get("working_path") == ""
    assert cfg.get("OutputText") == ""
    assert "schema" not in cfg
    assert "OutputText" in node.get_config_schema(None)
    assert list(node.get_config_schema(None).keys())[-1] == "working_path"

    out = node.on_input("ignored", {"OutputText": "hello-trigger"})
    routes = out.get("routes")
    assert isinstance(routes, list) and routes
    assert routes[0].get("output_index") == 0
    assert envelope_text(routes[0].get("payload")) == "hello-trigger"


def test_clock_node_outputs_config_text_and_defaults():
    from nodes.clock_node import Node

    node = Node()
    cfg = {}
    node.on_create(cfg, None)

    assert cfg.get("IntervalDays") == "0"
    assert cfg.get("IntervalHours") == "0"
    assert cfg.get("IntervalMinutes") == "1"
    assert cfg.get("IntervalSeconds") == "0"
    assert cfg.get("IsLoop") is True
    assert cfg.get("LoopCount") == "0"
    assert cfg.get("OutputText") == ""
    assert cfg.get("_clock_running") is False
    assert cfg.get("_clock_next_fire_at") is None
    assert cfg.get("_clock_remaining_seconds") is None
    assert cfg.get("_clock_trigger_count") == 0
    assert list(node.get_config_schema(None).keys())[:4] == [
        "IntervalDays",
        "IntervalHours",
        "IntervalMinutes",
        "IntervalSeconds",
    ]
    assert node.get_config_schema(None)["IntervalDays"]["type"] == "number"
    assert node.get_config_schema(None)["IsLoop"]["type"] == "boolean"
    assert node.get_config_schema(None)["LoopCount"]["type"] == "number"

    out = node.on_input("ignored", {"OutputText": "clock-fire"})
    routes = out.get("routes")
    assert isinstance(routes, list) and routes
    assert routes[0].get("output_index") == 0
    assert envelope_text(routes[0].get("payload")) == "clock-fire"


def test_clock_node_migrates_legacy_interval_seconds_to_time_parts():
    from nodes.clock_node import Node

    node = Node()
    cfg = {"IntervalSeconds": "3665"}
    node.on_create(cfg, None)

    assert cfg.get("IntervalDays") == "0"
    assert cfg.get("IntervalHours") == "1"
    assert cfg.get("IntervalMinutes") == "1"
    assert cfg.get("IntervalSeconds") == "5"


def test_clock_node_normalizes_overflowed_time_parts():
    from nodes.clock_node import Node

    node = Node()
    cfg = {"IntervalDays": "0", "IntervalHours": "0", "IntervalMinutes": "0", "IntervalSeconds": "65"}
    node.on_create(cfg, None)

    assert cfg.get("IntervalDays") == "0"
    assert cfg.get("IntervalHours") == "0"
    assert cfg.get("IntervalMinutes") == "1"
    assert cfg.get("IntervalSeconds") == "5"


def test_append_node_appends_text():
    from nodes.append_node import Node

    node = Node()
    cfg = {}
    node.on_create(cfg, None)

    out = node.on_input("abc", {"AppendText": "-tail"})
    routes = out.get("routes")
    assert isinstance(routes, list) and routes
    assert envelope_text(routes[0].get("payload")) == "abc-tail"


def test_save_file_node_uses_first_six_chars_when_filename_empty(tmp_path):
    from nodes.save_file_node import Node

    node = Node()
    content = "abcdefg-hello"
    out = node.on_input(content, {"FilePath": str(tmp_path), "FileName": ""})

    routes = out.get("routes")
    assert isinstance(routes, list) and routes
    assert envelope_text(routes[0].get("payload")) == content
    saved_path = tmp_path / "abcdef.md"
    assert saved_path.exists()
    assert saved_path.read_text(encoding="utf-8") == content


def test_save_file_node_preserves_existing_file_extension(tmp_path):
    from nodes.save_file_node import Node

    node = Node()
    content = "# report"
    out = node.on_input(content, {"FilePath": str(tmp_path), "FileName": "daily.txt"})

    routes = out.get("routes")
    assert isinstance(routes, list) and routes
    assert envelope_text(routes[0].get("payload")) == content
    saved_path = tmp_path / "daily.txt"
    assert saved_path.exists()
    assert saved_path.read_text(encoding="utf-8") == content


def test_timer_trigger_scan_enqueues_once_per_minute(monkeypatch, tmp_path):
    import src.web_backend.graph_timer_scheduler as timer_module
    from src.web_backend.core import BackendCore

    core = BackendCore()
    graph_runtime = core.graph_runtime

    monkeypatch.setattr(timer_module.runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(graph_runtime, "_ensure_graph_runner", lambda _graph_id: None)
    monkeypatch.setattr(graph_runtime, "_wake_graph_runner", lambda _graph_id: None)

    graph_id = "timer_graph"
    node_id = "timer_node"
    node_dir = tmp_path / "memories" / graph_id / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    config_path = node_dir / "config.json"
    config = {
        "node_id": node_id,
        "type_id": "timer_trigger_node",
        "state": "idle",
        "ScheduleAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "OutputText": "timer-fire",
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    first = graph_runtime._scan_and_emit_timer_triggers_once()
    assert first == 1

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    pending = updated.get("pending")
    assert isinstance(pending, list)
    assert len(pending) == 1
    assert envelope_text(pending[0].get("payload")) == "timer-fire"
    assert pending[0].get("source") == "timer_trigger"

    second = graph_runtime._scan_and_emit_timer_triggers_once()
    assert second == 0


def test_clock_control_start_sets_working_state(monkeypatch, tmp_path):
    from src.web_backend.core import BackendCore
    import src.web_backend.runtime_paths as runtime_paths

    core = BackendCore()
    graph_runtime = core.graph_runtime

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    graph_id = "clock_control_graph"
    node_id = "clock_control_node"
    node_dir = tmp_path / "memories" / graph_id / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    config_path = node_dir / "config.json"
    config = {
        "node_id": node_id,
        "type_id": "clock_node",
        "state": "idle",
        "IntervalDays": "0",
        "IntervalHours": "0",
        "IntervalMinutes": "0",
        "IntervalSeconds": "5",
        "IsLoop": "true",
        "LoopCount": "0",
        "OutputText": "clock-fire",
        "_clock_running": False,
        "_clock_next_fire_at": None,
        "_clock_remaining_seconds": None,
        "_clock_trigger_count": 0,
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    result = core.node_ops.control_node_instance(node_id, {"action": "start"}, graph_id)
    assert result["ok"] is True
    assert result["state"] == "working"

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated.get("_clock_running") is True
    assert updated.get("state") == "working"
    assert updated.get("_clock_trigger_count") == 0
    assert str(updated.get("last_message") or "").startswith("Working")


def test_clock_trigger_scan_requires_start_and_enqueues_after_interval(monkeypatch, tmp_path):
    import src.web_backend.graph_timer_scheduler as timer_module
    from src.web_backend.core import BackendCore

    core = BackendCore()
    graph_runtime = core.graph_runtime

    monkeypatch.setattr(timer_module.runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(graph_runtime, "_ensure_graph_runner", lambda _graph_id: None)
    monkeypatch.setattr(graph_runtime, "_wake_graph_runner", lambda _graph_id: None)

    graph_id = "clock_graph"
    node_id = "clock_node_1"
    node_dir = tmp_path / "memories" / graph_id / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    config_path = node_dir / "config.json"
    config = {
        "node_id": node_id,
        "type_id": "clock_node",
        "state": "idle",
        "IntervalDays": "0",
        "IntervalHours": "0",
        "IntervalMinutes": "0",
        "IntervalSeconds": "5",
        "IsLoop": "true",
        "LoopCount": "0",
        "OutputText": "clock-fire",
        "_clock_running": False,
        "_clock_next_fire_at": None,
        "_clock_remaining_seconds": None,
        "_clock_trigger_count": 0,
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    first = graph_runtime._scan_and_emit_scheduled_nodes_once()
    assert first == 0

    idle_cfg = json.loads(config_path.read_text(encoding="utf-8"))
    assert idle_cfg.get("pending") is None
    assert idle_cfg.get("_clock_running") is False

    started = core.node_ops.control_node_instance(node_id, {"action": "start"}, graph_id)
    assert started["state"] == "working"

    started_cfg = json.loads(config_path.read_text(encoding="utf-8"))
    started_cfg["_clock_next_fire_at"] = time.time() - 0.1
    config_path.write_text(json.dumps(started_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    second = graph_runtime._scan_and_emit_scheduled_nodes_once()
    assert second == 1

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    pending = updated.get("pending")
    assert isinstance(pending, list)
    assert len(pending) == 1
    assert envelope_text(pending[0].get("payload")) == "clock-fire"
    assert pending[0].get("source") == "clock_trigger"
    assert updated.get("_clock_running") is True
    assert updated.get("_clock_trigger_count") == 1
    assert updated.get("state") == "working"

    third = graph_runtime._scan_and_emit_scheduled_nodes_once()
    assert third == 0


def test_clock_trigger_respects_loop_count_and_stops_after_limit(monkeypatch, tmp_path):
    import src.web_backend.graph_timer_scheduler as timer_module
    from src.web_backend.core import BackendCore

    core = BackendCore()
    graph_runtime = core.graph_runtime

    monkeypatch.setattr(timer_module.runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(graph_runtime, "_ensure_graph_runner", lambda _graph_id: None)
    monkeypatch.setattr(graph_runtime, "_wake_graph_runner", lambda _graph_id: None)

    graph_id = "clock_graph_limit"
    node_id = "clock_node_limit"
    node_dir = tmp_path / "memories" / graph_id / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    config_path = node_dir / "config.json"
    config = {
        "node_id": node_id,
        "type_id": "clock_node",
        "state": "idle",
        "IntervalDays": "0",
        "IntervalHours": "0",
        "IntervalMinutes": "0",
        "IntervalSeconds": "5",
        "IsLoop": "true",
        "LoopCount": "1",
        "OutputText": "clock-fire",
        "_clock_running": True,
        "_clock_next_fire_at": time.time() - 0.1,
        "_clock_remaining_seconds": 0,
        "_clock_trigger_count": 0,
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    first = graph_runtime._scan_and_emit_scheduled_nodes_once()
    assert first == 1

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated.get("_clock_running") is False
    assert updated.get("_clock_trigger_count") == 1
    assert updated.get("state") == "idle"
    assert str(updated.get("last_message") or "").startswith("Completed")

    second = graph_runtime._scan_and_emit_scheduled_nodes_once()
    assert second == 0


def test_clock_control_supports_legacy_interval_seconds(monkeypatch, tmp_path):
    from src.web_backend.core import BackendCore
    import src.web_backend.runtime_paths as runtime_paths

    core = BackendCore()

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    graph_id = "clock_control_legacy_graph"
    node_id = "clock_control_legacy_node"
    node_dir = tmp_path / "memories" / graph_id / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    config_path = node_dir / "config.json"
    config = {
        "node_id": node_id,
        "type_id": "clock_node",
        "state": "idle",
        "IntervalSeconds": "65",
        "IsLoop": "true",
        "LoopCount": "0",
        "OutputText": "clock-fire",
        "_clock_running": False,
        "_clock_next_fire_at": None,
        "_clock_remaining_seconds": None,
        "_clock_trigger_count": 0,
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    result = core.node_ops.control_node_instance(node_id, {"action": "start"}, graph_id)
    assert result["ok"] is True

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated.get("IntervalDays") == "0"
    assert updated.get("IntervalHours") == "0"
    assert updated.get("IntervalMinutes") == "1"
    assert updated.get("IntervalSeconds") == "5"


def test_multi_input_node_waits_until_all_ports_receive_messages(monkeypatch, tmp_path):
    import nodes.base_node as base_node_module
    from nodes.multi_input_node import Node

    monkeypatch.setattr(base_node_module, "_get_runtime_root", lambda: str(tmp_path))

    node = Node()
    graph_id = "multi_graph"
    node_id = "multi_node"
    ctx = {"graph_id": graph_id, "node_instance_id": node_id, "node_type_id": "multi_input_node"}
    cfg = {}
    node.on_create(cfg, ctx)

    node_dir = tmp_path / "memories" / graph_id / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    config_path = node_dir / "config.json"
    config_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    first = node.on_input("A", {**ctx, "input_index": 0, "InputCount": "2"})
    assert first.get("suppress_output") is True
    assert first.get("routes") == []
    assert first.get("display") == "waiting 1/2"

    second = node.on_input("B", {**ctx, "input_index": 1, "InputCount": "2"})
    routes = second.get("routes")
    assert isinstance(routes, list) and routes
    assert routes[0].get("output_index") == 0
    assert envelope_text(routes[0].get("payload")) == "AB"

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved.get("_multi_input_buffer") == [None, None]


def test_loop_node_routes_continue_until_remaining_count_reaches_zero(monkeypatch, tmp_path):
    import nodes.base_node as base_node_module
    from nodes.loop_node import Node

    monkeypatch.setattr(base_node_module, "_get_runtime_root", lambda: str(tmp_path))

    node = Node()
    graph_id = "loop_graph"
    node_id = "loop_node"
    ctx = {"graph_id": graph_id, "node_instance_id": node_id, "node_type_id": "loop_node"}
    cfg = {}
    node.on_create(cfg, ctx)

    assert cfg.get("LoopCount") == "1"
    assert "schema" not in cfg
    assert node.get_config_schema(None)["LoopCount"]["type"] == "number"
    assert node.getOutputNum(ctx) == 2

    node_dir = tmp_path / "memories" / graph_id / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    config_path = node_dir / "config.json"
    persisted_cfg = dict(cfg)
    persisted_cfg["LoopCount"] = "2"
    config_path.write_text(json.dumps(persisted_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    first = node.on_input("step-1", {**ctx, "LoopCount": "2"})
    first_routes = first.get("routes")
    assert isinstance(first_routes, list) and first_routes
    assert first_routes[0].get("output_index") == 0
    assert envelope_text(first_routes[0].get("payload")) == "step-1"

    first_saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert first_saved.get("_loop_remaining") == 1

    second = node.on_input("step-2", {**ctx, "LoopCount": "2"})
    second_routes = second.get("routes")
    assert isinstance(second_routes, list) and second_routes
    assert second_routes[0].get("output_index") == 0
    assert envelope_text(second_routes[0].get("payload")) == "step-2"

    second_saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert second_saved.get("_loop_remaining") == 0


def test_loop_node_routes_finish_and_resets_remaining_count(monkeypatch, tmp_path):
    import nodes.base_node as base_node_module
    from nodes.loop_node import Node

    monkeypatch.setattr(base_node_module, "_get_runtime_root", lambda: str(tmp_path))

    node = Node()
    graph_id = "loop_graph_finish"
    node_id = "loop_node_finish"
    ctx = {"graph_id": graph_id, "node_instance_id": node_id, "node_type_id": "loop_node"}

    node_dir = tmp_path / "memories" / graph_id / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    config_path = node_dir / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "LoopCount": "2",
                "_loop_remaining": 0,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    out = node.on_input("done", {**ctx, "LoopCount": "2"})
    routes = out.get("routes")
    assert isinstance(routes, list) and routes
    assert routes[0].get("output_index") == 1
    assert envelope_text(routes[0].get("payload")) == "done"

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved.get("_loop_remaining") == 2
