import time
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


def test_runner_recovers_working_node_without_inflight(tmp_path):
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

