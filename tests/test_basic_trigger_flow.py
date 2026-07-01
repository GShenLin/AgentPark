import time
import json
from datetime import datetime, timedelta


def test_basic_trigger_node_click_emit_flows_to_next_node(tmp_path):
    import src.web_backend as backend

    runtime_root = str(tmp_path)
    original_get_runtime_root = backend._get_runtime_root
    original_get_resource_root = backend._get_resource_root
    resource_root = original_get_runtime_root()

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root

    try:
        app = backend.create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)

        graph = {
            "id": "default",
            "name": "default",
            "nodes": [
                {"id": "t1", "typeId": "basic_trigger_node", "name": "t1", "ui": {"x": 0, "y": 0}},
                {"id": "a1", "typeId": "append_node", "name": "a1", "ui": {"x": 120, "y": 0}},
            ],
            "links": [
                {
                    "id": "l1",
                    "from": {"node": "t1", "index": 0},
                    "to": {"node": "a1", "index": 0},
                }
            ],
        }

        assert client.post("/api/graphs/default", json={"graph": graph}).status_code == 200
        assert (
            client.post(
                "/api/nodes/instances",
                json={"node_id": "t1", "type_id": "basic_trigger_node", "graph_id": "default"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/nodes/instances",
                json={"node_id": "a1", "type_id": "append_node", "graph_id": "default"},
            ).status_code
            == 200
        )

        assert (
            client.post(
                "/api/nodes/instances/t1/config?graph_id=default",
                json={"fields": {"OutputText": "hello-trigger"}},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/nodes/instances/a1/config?graph_id=default",
                json={"fields": {"AppendText": "-done"}},
            ).status_code
            == 200
        )

        assert client.post("/api/graphs/default/runner/start").status_code == 200
        assert client.post("/api/graphs/default/emit", json={"from_id": "t1", "payload": ""}).status_code == 200

        ok = False
        for _ in range(40):
            cfgs = client.get("/api/nodes/instances/configs?graph_id=default")
            if cfgs.status_code == 200:
                nodes = cfgs.json().get("nodes") or []
                a1_cfg = next((item for item in nodes if str(item.get("node_id") or "") == "a1"), None)
                if isinstance(a1_cfg, dict) and str(a1_cfg.get("last_message") or "") == "hello-trigger-done":
                    ok = True
                    break
            time.sleep(0.1)

        assert ok, "basic_trigger_node output was not propagated to append_node"
    finally:
        backend._get_runtime_root = original_get_runtime_root
        backend._get_resource_root = original_get_resource_root


def test_console_command_trigger_persists_config_command_as_user_message(tmp_path):
    import src.web_backend as backend

    runtime_root = str(tmp_path)
    original_get_runtime_root = backend._get_runtime_root
    original_get_resource_root = backend._get_resource_root
    resource_root = original_get_runtime_root()

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root

    try:
        app = backend.create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)

        graph = {
            "id": "default",
            "name": "default",
            "nodes": [
                {"id": "cmd1", "typeId": "console_command_node", "name": "cmd1", "ui": {"x": 0, "y": 0}},
            ],
            "links": [],
        }
        assert client.post("/api/graphs/default", json={"graph": graph}).status_code == 200
        assert (
            client.post(
                "/api/nodes/instances",
                json={"node_id": "cmd1", "type_id": "console_command_node", "graph_id": "default"},
            ).status_code
            == 200
        )
        command = "echo hello-from-config"
        assert (
            client.post(
                "/api/nodes/instances/cmd1/config?graph_id=default",
                json={"fields": {"Command": command}},
            ).status_code
            == 200
        )

        assert client.post("/api/graphs/default/runner/start").status_code == 200
        response = client.post("/api/graphs/default/emit", json={"from_id": "cmd1", "payload": ""})
        assert response.status_code == 200

        mem = client.get("/api/nodes/instances/cmd1/memory?graph_id=default&max_chars=20000")
        assert mem.status_code == 200
        messages = mem.json().get("messages") or []
        user_messages = [item for item in messages if isinstance(item, dict) and item.get("role") == "user"]
        assert user_messages
        assert user_messages[0]["parts"] == [{"type": "text", "text": command}]
    finally:
        backend._get_runtime_root = original_get_runtime_root
        backend._get_resource_root = original_get_resource_root


def test_runner_recovers_working_node_without_inflight(tmp_path):
    import src.web_backend as backend
    import src.web_backend.runtime_paths as runtime_paths_module

    runtime_root = str(tmp_path)
    original_get_runtime_root = backend._get_runtime_root
    original_get_resource_root = backend._get_resource_root
    original_runtime_paths_get_runtime_root = runtime_paths_module._get_runtime_root
    original_runtime_paths_get_resource_root = runtime_paths_module._get_resource_root
    resource_root = original_get_runtime_root()

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root
    runtime_paths_module._get_runtime_root = lambda: runtime_root
    runtime_paths_module._get_resource_root = lambda: resource_root

    try:
        app = backend.create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)

        graph = {"id": "default", "name": "default", "nodes": [], "links": []}
        assert client.post("/api/graphs/default", json={"graph": graph}).status_code == 200
        assert (
            client.post(
                "/api/nodes/instances",
                json={"node_id": "e1", "type_id": "echo_node", "graph_id": "default"},
            ).status_code
            == 200
        )

        assert client.post("/api/graphs/default/runner/start").status_code == 200
        assert client.post("/api/nodes/instances/e1/state?graph_id=default", json={"state": "working"}).status_code == 200
        assert (
            client.post(
                "/api/nodes/instances/e1/pending?graph_id=default",
                json={"payload": "recover-me", "trace_id": "recover-trace", "source": "test"},
            ).status_code
            == 200
        )

        recovered = False
        for _ in range(50):
            cfgs = client.get("/api/nodes/instances/configs?graph_id=default")
            if cfgs.status_code == 200:
                nodes = cfgs.json().get("nodes") or []
                cfg = next((item for item in nodes if str(item.get("node_id") or "") == "e1"), None)
                if (
                    isinstance(cfg, dict)
                    and str(cfg.get("state") or "") == "idle"
                    and int(cfg.get("pending_count") or 0) == 0
                    and str(cfg.get("last_message") or "") == "recover-me"
                ):
                    recovered = True
                    break
            time.sleep(0.1)

        assert recovered, "runner failed to recover working node without inflight and process pending message"
    finally:
        backend._get_runtime_root = original_get_runtime_root
        backend._get_resource_root = original_get_resource_root
        runtime_paths_module._get_runtime_root = original_runtime_paths_get_runtime_root
        runtime_paths_module._get_resource_root = original_runtime_paths_get_resource_root


def test_startup_recovery_requeues_inflight_and_logs_reason(tmp_path):
    import src.web_backend as backend
    import src.web_backend.runtime_paths as runtime_paths_module

    runtime_root = str(tmp_path)
    original_get_runtime_root = backend._get_runtime_root
    original_get_resource_root = backend._get_resource_root
    original_runtime_paths_get_runtime_root = runtime_paths_module._get_runtime_root
    original_runtime_paths_get_resource_root = runtime_paths_module._get_resource_root
    resource_root = original_get_runtime_root()

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root
    runtime_paths_module._get_runtime_root = lambda: runtime_root
    runtime_paths_module._get_resource_root = lambda: resource_root

    try:
        graph_id = "startup_recovery_graph"
        graph_dir = tmp_path / "memories" / graph_id
        node_dir = graph_dir / "agent1"
        node_dir.mkdir(parents=True)
        config_path = node_dir / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "node_id": "agent1",
                    "type_id": "agent_node",
                    "state": "working",
                    "pending": [{"payload": "queued"}],
                    "pending_count": 1,
                    "inflight": {"payload": "running"},
                    "_stop_requested": True,
                }
            ),
            encoding="utf-8",
        )

        facade = backend.WebBackendFacade()
        recovery = facade.core.graph_runtime._recover_node_runtime_state_on_startup()

        from src.web_backend.node_config_service import node_runtime_state_path

        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        runtime_cfg = json.loads(open(node_runtime_state_path(str(config_path)), "r", encoding="utf-8").read())
        assert recovery["inflight_requeued"] == 1
        assert recovery["nodes_reset_to_idle"] == 1
        assert recovery["graphs_woken"] == 1
        for key in ("state", "pending", "pending_count", "inflight", "_stop_requested"):
            assert key not in cfg
        assert runtime_cfg["state"] == "idle"
        assert runtime_cfg["pending"] == [{"payload": "running"}, {"payload": "queued"}]
        assert runtime_cfg["pending_count"] == 2
        assert "inflight" not in runtime_cfg
        assert "_stop_requested" not in runtime_cfg

        events_path = graph_dir / "runner.events.jsonl"
        events = [
            json.loads(line)
            for line in events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        recovered_event = next(item for item in events if item.get("event") == "startup_node_state_recovered")
        assert recovered_event["before_state"] == "working"
        assert recovered_event["after_state"] == "idle"
        assert recovered_event["reason"] == "startup_inflight_requeued"
        assert recovered_event["inflight_requeued"] is True
        assert recovered_event["pending_count"] == 2
    finally:
        backend._get_runtime_root = original_get_runtime_root
        backend._get_resource_root = original_get_resource_root
        runtime_paths_module._get_runtime_root = original_runtime_paths_get_runtime_root
        runtime_paths_module._get_resource_root = original_runtime_paths_get_resource_root


def test_startup_recovery_preserves_stop_state(tmp_path):
    from src.web_backend.state_store import _read_json_dict, _recover_node_config_startup_state, _write_json_dict

    config_path = tmp_path / "node" / "config.json"
    _write_json_dict(
        str(config_path),
        {
            "node_id": "agent1",
            "type_id": "agent_node",
            "state": "stop",
            "pending": [{"payload": "queued"}],
            "pending_count": 1,
            "inflight": {"payload": "running"},
            "_stop_requested": True,
        },
    )

    recovery = _recover_node_config_startup_state(str(config_path))
    cfg = _read_json_dict(str(config_path))

    assert recovery["recovered"] is False
    assert recovery["reason"] == "stop_state_preserved"
    assert recovery["before_state"] == "stop"
    assert recovery["after_state"] == "stop"
    assert cfg["state"] == "stop"
    assert cfg["pending"] == [{"payload": "queued"}]
    assert cfg["inflight"] == {"payload": "running"}
    assert cfg["_stop_requested"] is True


def test_stale_working_node_with_inflight_is_not_requeued_by_timeout(tmp_path):
    from src.web_backend.state_store import _recover_node_config_stale_working, _write_json_dict

    config_path = tmp_path / "node" / "config.json"
    old_timestamp = (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S.%f")
    _write_json_dict(
        str(config_path),
        {
            "node_id": "video1",
            "type_id": "video_generation_node",
            "state": "working",
            "pending": [],
            "pending_count": 0,
            "inflight": {"payload": "keep-running"},
            "inflight_at": old_timestamp,
        },
    )

    recovered = _recover_node_config_stale_working(str(config_path), stale_seconds=120)

    assert recovered == {"recovered": False, "reason": "", "pending_count": 0}

