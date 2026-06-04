import json
import os
import shutil
import uuid


def test_graph_config_strips_nodes_field():
    import src.web_backend as backend

    graph_id = f"ut_strip_nodes_{uuid.uuid4().hex[:8]}"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    try:
        client = TestClient(app)
        graph = {
            "id": graph_id,
            "name": graph_id,
            "nodes": [{"id": "x", "typeId": "append_node", "name": "x", "ui": {"x": 1, "y": 2}}],
            "links": [],
        }
        r = client.post(f"/api/graphs/{graph_id}", json={"graph": graph})
        assert r.status_code == 200

        config_path = os.path.join(_get_graphs_dir(), graph_id, "config.json")
        saved = json.loads(open(config_path, "r", encoding="utf-8").read())
        assert "nodes" not in saved
        assert saved.get("links") == []

        loaded = client.get(f"/api/graphs/{graph_id}").json().get("graph") or {}
        assert "nodes" not in loaded
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)
