import os
import shutil


def test_mobile_api_lists_current_pc_graphs_nodes_and_sends_message(monkeypatch, tmp_path):
    import src.web_backend as backend
    import src.web_backend.mobile_api as mobile_api_module
    import src.web_backend.node_runtime as node_runtime_module
    import src.web_backend.runtime_paths as runtime_paths_module

    runtime_root = str(tmp_path / "AITools")
    resource_root = backend._get_runtime_root()
    os.makedirs(runtime_root, exist_ok=True)

    original_backend_runtime_root = backend._get_runtime_root
    original_backend_resource_root = backend._get_resource_root
    original_runtime_paths_runtime_root = runtime_paths_module._get_runtime_root
    original_runtime_paths_resource_root = runtime_paths_module._get_resource_root
    original_node_runtime_runtime_root = node_runtime_module._get_runtime_root
    original_node_runtime_resource_root = node_runtime_module._get_resource_root
    original_mobile_runtime_root = mobile_api_module._get_runtime_root

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root
    runtime_paths_module._get_runtime_root = lambda: runtime_root
    runtime_paths_module._get_resource_root = lambda: resource_root
    node_runtime_module._get_runtime_root = lambda: runtime_root
    node_runtime_module._get_resource_root = lambda: resource_root
    mobile_api_module._get_runtime_root = lambda: runtime_root

    try:
        app = backend.create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)

        graph = {"id": "default", "name": "Default", "links": []}
        assert client.post("/api/graphs/default", json={"graph": graph}).status_code == 200
        create_node = client.post(
            "/api/nodes/instances",
            json={"node_id": "agent1", "type_id": "agent_node", "name": "Agent 1", "graph_id": "default"},
        )
        assert create_node.status_code == 200

        pcs = client.get("/api/mobile/pcs")
        assert pcs.status_code == 200
        assert pcs.json()["pcs"][0]["id"] == "local"
        assert pcs.json()["pcs"][0]["instances"][0]["name"] == "AITools"

        graphs = client.get("/api/mobile/pcs/local/graphs")
        assert graphs.status_code == 200
        graph_item = graphs.json()["instances"][0]["graphs"][0]
        assert graph_item["id"] == "default"
        assert graph_item["display_name"] == "AITools.Default"

        nodes = client.get("/api/mobile/pcs/local/graphs/default/nodes")
        assert nodes.status_code == 200
        assert nodes.json()["nodes"][0]["id"] == "agent1"

        sent = client.post(
            "/api/mobile/pcs/local/graphs/default/nodes/agent1/messages",
            json={"message": "hello from phone"},
        )
        assert sent.status_code == 200
        assert sent.json()["queued"] is True

        cfgs = client.get("/api/nodes/instances/configs?graph_id=default").json()["nodes"]
        cfg = next(item for item in cfgs if item["node_id"] == "agent1")
        assert cfg["pending_count"] == 1
        assert cfg["last_message"] == "hello from phone"
    finally:
        backend._get_runtime_root = original_backend_runtime_root
        backend._get_resource_root = original_backend_resource_root
        runtime_paths_module._get_runtime_root = original_runtime_paths_runtime_root
        runtime_paths_module._get_resource_root = original_runtime_paths_resource_root
        node_runtime_module._get_runtime_root = original_node_runtime_runtime_root
        node_runtime_module._get_resource_root = original_node_runtime_resource_root
        mobile_api_module._get_runtime_root = original_mobile_runtime_root
        shutil.rmtree(runtime_root, ignore_errors=True)


def test_mobile_api_rejects_unknown_pc():
    import src.web_backend as backend
    from fastapi.testclient import TestClient

    client = TestClient(backend.create_app())
    response = client.get("/api/mobile/pcs/missing/graphs")

    assert response.status_code == 404
