import json
import os
import shutil
import uuid


def test_update_node_instance_config_persists_ui():
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_ui_{uuid.uuid4().hex[:8]}"
    node_id = "n1"
    app = backend.create_app()
    from fastapi.testclient import TestClient

    try:
        client = TestClient(app)
        r = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": graph_id, "ui": {"x": 1, "y": 2}},
        )
        assert r.status_code == 200

        r = client.post(
            f"/api/nodes/instances/{node_id}/config?graph_id={graph_id}",
            json={"ui": {"x": 321, "y": 654}},
        )
        assert r.status_code == 200

        config_path = os.path.join(_get_graphs_dir(), graph_id, node_id, "config.json")
        payload = json.loads(open(config_path, "r", encoding="utf-8").read())
        ui = payload.get("ui") if isinstance(payload, dict) else None
        assert isinstance(ui, dict)
        assert ui.get("x") == 321
        assert ui.get("y") == 654
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_list_node_instance_configs_migrates_missing_working_path():
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_working_path_{uuid.uuid4().hex[:8]}"
    node_id = "legacy_node"
    app = backend.create_app()
    from fastapi.testclient import TestClient

    try:
        client = TestClient(app)
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": graph_id, "ui": {"x": 1, "y": 2}},
        )
        assert created.status_code == 200

        config_path = os.path.join(_get_graphs_dir(), graph_id, node_id, "config.json")
        payload = json.loads(open(config_path, "r", encoding="utf-8").read())
        payload.pop("working_path", None)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        response = client.get(f"/api/nodes/instances/configs?graph_id={graph_id}")
        assert response.status_code == 200
        nodes = response.json().get("nodes") or []
        cfg = next(item for item in nodes if str(item.get("node_id") or "") == node_id)
        assert cfg.get("working_path") == ""

        saved = json.loads(open(config_path, "r", encoding="utf-8").read())
        assert saved.get("working_path") == ""
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_update_node_instance_config_recomputes_dynamic_input_ports():
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_ports_{uuid.uuid4().hex[:8]}"
    node_id = "multi1"
    app = backend.create_app()
    from fastapi.testclient import TestClient

    try:
        client = TestClient(app)
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "multi_input_node", "graph_id": graph_id, "ui": {"x": 1, "y": 2}},
        )
        assert created.status_code == 200

        config_path = os.path.join(_get_graphs_dir(), graph_id, node_id, "config.json")
        created_cfg = json.loads(open(config_path, "r", encoding="utf-8").read())
        assert created_cfg.get("input_num") == 2

        updated = client.post(
            f"/api/nodes/instances/{node_id}/config?graph_id={graph_id}",
            json={"fields": {"InputCount": "3"}},
        )
        assert updated.status_code == 200

        payload = json.loads(open(config_path, "r", encoding="utf-8").read())
        assert payload.get("InputCount") == "3"
        assert payload.get("input_num") == 3
        assert payload.get("output_num") == 1
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_create_loop_node_instance_persists_two_output_ports():
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_loop_ports_{uuid.uuid4().hex[:8]}"
    node_id = "loop1"
    app = backend.create_app()
    from fastapi.testclient import TestClient

    try:
        client = TestClient(app)
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "loop_node", "graph_id": graph_id, "ui": {"x": 1, "y": 2}},
        )
        assert created.status_code == 200

        config_path = os.path.join(_get_graphs_dir(), graph_id, node_id, "config.json")
        payload = json.loads(open(config_path, "r", encoding="utf-8").read())
        assert payload.get("LoopCount") == "1"
        assert payload.get("input_num") == 1
        assert payload.get("output_num") == 2
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_get_node_instance_memory_returns_empty_payload_before_any_history_exists():
    import src.web_backend as backend

    graph_id = f"ut_empty_memory_{uuid.uuid4().hex[:8]}"
    node_id = "empty_node"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    try:
        client = TestClient(app)
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": graph_id, "ui": {"x": 1, "y": 2}},
        )
        assert created.status_code == 200

        response = client.get(f"/api/nodes/instances/{node_id}/memory?graph_id={graph_id}&max_chars=20000")
        assert response.status_code == 200
        payload = response.json()
        assert payload.get("text") == ""
        assert payload.get("messages") == []
        assert payload.get("state") == "idle"
        assert payload.get("last_message") == ""
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_get_node_template_reports_metadata_load_errors(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths

    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir()
    broken_node = nodes_dir / "broken_template_node.py"
    broken_node.write_text("raise RuntimeError('template boom')\n", encoding="utf-8")
    monkeypatch.setattr(runtime_paths, "_get_nodes_dir", lambda: str(nodes_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_resource_root", lambda: str(tmp_path))

    app = backend.create_app()
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.get("/api/nodes/templates/broken_template_node")

    assert response.status_code == 500
    assert "Error loading node module" in response.json().get("detail", "")


def test_create_node_instance_reports_on_create_metadata_errors(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths

    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir()
    node_source = """
class Node:
    def on_create(self, config, context):
        raise RuntimeError('on create boom')
"""
    (nodes_dir / "bad_create_node.py").write_text(node_source, encoding="utf-8")
    monkeypatch.setattr(runtime_paths, "_get_nodes_dir", lambda: str(nodes_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_resource_root", lambda: str(tmp_path))

    app = backend.create_app()
    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.post(
        "/api/nodes/instances",
        json={"node_id": "bad_create", "type_id": "bad_create_node", "graph_id": "ut_bad_create"},
    )

    assert response.status_code == 500
    assert "on create boom" in response.json().get("detail", "")


def test_delete_node_instance_reports_delete_failures(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    app = backend.create_app()
    from fastapi.testclient import TestClient

    client = TestClient(app)
    created = client.post(
        "/api/nodes/instances",
        json={"node_id": "delete_fail", "type_id": "missing_node", "graph_id": "ut_delete_fail"},
    )
    assert created.status_code == 200

    def fail_rmtree(_path):
        raise OSError("delete boom")

    monkeypatch.setattr(shutil, "rmtree", fail_rmtree)
    response = client.delete("/api/nodes/instances/delete_fail?graph_id=ut_delete_fail")

    assert response.status_code == 500
    assert "delete boom" in response.json().get("detail", "")
