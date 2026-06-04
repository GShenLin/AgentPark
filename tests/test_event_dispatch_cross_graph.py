import os
import time
from pathlib import Path


def test_event_dispatch_cross_graph(tmp_path):
    import src.web_backend as backend

    runtime_root = str(tmp_path)

    original_get_runtime_root = backend._get_runtime_root
    original_get_resource_root = backend._get_resource_root
    resource_root = original_get_runtime_root()

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root

    try:
        graphs_dir = Path(runtime_root) / "memories"
        nodes_mem_dir = graphs_dir / "g2"
        os.makedirs(nodes_mem_dir, exist_ok=True)

        app = backend.create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)

        g1 = {
            "id": "g1",
            "name": "g1",
            "nodes": [
                {"id": "ev_src", "typeId": "event_node", "name": "ev_src", "ui": {"x": 0, "y": 0}},
            ],
            "links": [],
        }
        g2 = {
            "id": "g2",
            "name": "g2",
            "nodes": [
                {"id": "ev_dst", "typeId": "event_node", "name": "ev_dst", "ui": {"x": 0, "y": 0}},
                {"id": "echo_dst", "typeId": "echo_node", "name": "echo_dst", "ui": {"x": 100, "y": 0}},
            ],
            "links": [
                {
                    "id": "l1",
                    "from": {"node": "ev_dst", "index": 0},
                    "to": {"node": "echo_dst", "index": 0},
                }
            ],
        }

        r = client.post("/api/graphs/g1", json={"graph": g1})
        assert r.status_code == 200
        r = client.post("/api/graphs/g2", json={"graph": g2})
        assert r.status_code == 200

        r = client.post("/api/nodes/instances", json={"node_id": "ev_src", "type_id": "event_node", "graph_id": "g1"})
        assert r.status_code == 200
        r = client.post("/api/nodes/instances", json={"node_id": "ev_dst", "type_id": "event_node", "graph_id": "g2"})
        assert r.status_code == 200
        r = client.post("/api/nodes/instances", json={"node_id": "echo_dst", "type_id": "echo_node", "graph_id": "g2"})
        assert r.status_code == 200

        r = client.post(
            "/api/nodes/instances/ev_src/config?graph_id=g1",
            json={"fields": {"EventKey": "MyEvent"}},
        )
        assert r.status_code == 200

        r = client.post(
            "/api/nodes/instances/ev_dst/config?graph_id=g2",
            json={"fields": {"EventKey": "MyEvent"}},
        )
        assert r.status_code == 200

        r = client.post("/api/graphs/g1/runner/start")
        assert r.status_code == 200
        r = client.post("/api/graphs/g2/runner/start")
        assert r.status_code == 200

        r = client.post(
            "/api/graphs/g1/emit",
            json={"from_id": "ev_src", "payload": "hello-event"},
        )
        assert r.status_code == 200

        ok = False
        for _ in range(40):
            cfgs = client.get("/api/nodes/instances/configs?graph_id=g2")
            if cfgs.status_code == 200:
                nodes = cfgs.json().get("nodes") or []
                echo_cfg = next((item for item in nodes if str(item.get("node_id") or "") == "echo_dst"), None)
                if isinstance(echo_cfg, dict) and "hello-event" in str(echo_cfg.get("last_message") or ""):
                    ok = True
                    break
            time.sleep(0.1)

        assert ok, "echo_dst did not receive cross-graph event payload"
    finally:
        backend._get_runtime_root = original_get_runtime_root
        backend._get_resource_root = original_get_resource_root
