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


def test_graph_copy_artifacts_retargets_node_configs_and_skips_runner_log():
    import src.web_backend as backend

    source_graph_id = f"ut_copy_src_{uuid.uuid4().hex[:8]}"
    target_graph_id = f"ut_copy_dst_{uuid.uuid4().hex[:8]}"
    node_id = "Agent"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    graphs_dir = _get_graphs_dir()
    source_dir = os.path.join(graphs_dir, source_graph_id)
    target_dir = os.path.join(graphs_dir, target_graph_id)
    try:
        os.makedirs(os.path.join(source_dir, node_id), exist_ok=True)
        with open(os.path.join(source_dir, "config.json"), "w", encoding="utf-8") as handle:
            json.dump({"id": source_graph_id, "name": source_graph_id, "links": []}, handle)
        with open(os.path.join(source_dir, "runner.events.jsonl"), "w", encoding="utf-8") as handle:
            handle.write('{"event":"old"}\n')
        with open(os.path.join(source_dir, node_id, "config.json"), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "node_id": node_id,
                    "type_id": "agent_node",
                    "name": node_id,
                    "graph_id": source_graph_id,
                },
                handle,
            )

        response = TestClient(app).post(
            f"/api/graphs/{target_graph_id}",
            json={
                "graph": {"id": target_graph_id, "name": target_graph_id, "links": []},
                "source_graph_id": source_graph_id,
            },
        )

        assert response.status_code == 200
        copied_config_path = os.path.join(target_dir, node_id, "config.json")
        copied_config = json.loads(open(copied_config_path, "r", encoding="utf-8").read())
        assert copied_config["node_id"] == node_id
        assert copied_config["graph_id"] == target_graph_id
        runner_log = os.path.join(target_dir, "runner.events.jsonl")
        if os.path.exists(runner_log):
            assert '{"event":"old"}' not in open(runner_log, "r", encoding="utf-8").read()
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)
        shutil.rmtree(target_dir, ignore_errors=True)


def test_graph_load_supports_version_unchanged_response():
    import src.web_backend as backend

    graph_id = f"ut_graph_version_{uuid.uuid4().hex[:8]}"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    try:
        client = TestClient(app)
        graph = {
            "id": graph_id,
            "name": graph_id,
            "nodes": [],
            "links": [{"id": "l1", "from": {"node": "a", "index": 0}, "to": {"node": "b", "index": 0}}],
        }
        r = client.post(f"/api/graphs/{graph_id}", json={"graph": graph})
        assert r.status_code == 200

        loaded = client.get(f"/api/graphs/{graph_id}")
        assert loaded.status_code == 200
        payload = loaded.json().get("graph") or {}
        version = int(payload.get("version") or 0)
        assert version > 0
        assert payload.get("links")

        unchanged = client.get(f"/api/graphs/{graph_id}?if_version={version}")
        assert unchanged.status_code == 200
        unchanged_payload = unchanged.json().get("graph") or {}
        assert unchanged_payload == {"id": graph_id, "version": version, "unchanged": True}
    finally:
        shutil.rmtree(os.path.join(_get_graphs_dir(), graph_id), ignore_errors=True)


def test_graph_load_rejects_non_object_config():
    import src.web_backend as backend

    graph_id = f"ut_graph_bad_{uuid.uuid4().hex[:8]}"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_dir = os.path.join(_get_graphs_dir(), graph_id)
    try:
        os.makedirs(graph_dir, exist_ok=True)
        with open(os.path.join(graph_dir, "config.json"), "w", encoding="utf-8") as handle:
            handle.write("[]")

        response = TestClient(app).get(f"/api/graphs/{graph_id}")

        assert response.status_code == 500
        assert "JSON object" in response.json().get("detail", "")
    finally:
        shutil.rmtree(graph_dir, ignore_errors=True)


def test_graph_list_rejects_corrupt_config():
    import src.web_backend as backend

    graph_id = f"ut_graph_list_bad_{uuid.uuid4().hex[:8]}"
    app = backend.create_app()
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_dir = os.path.join(_get_graphs_dir(), graph_id)
    try:
        os.makedirs(graph_dir, exist_ok=True)
        with open(os.path.join(graph_dir, "config.json"), "w", encoding="utf-8") as handle:
            handle.write("{bad")

        response = TestClient(app).get("/api/graphs")

        assert response.status_code == 500
        assert "invalid JSON" in response.json().get("detail", "")
        assert graph_id in response.json().get("detail", "")
    finally:
        shutil.rmtree(graph_dir, ignore_errors=True)


def test_runtime_graph_read_rejects_non_object_config(tmp_path, monkeypatch):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.web_backend.graph_runtime_registry import GraphConfigReadError

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    graph_dir = tmp_path / "memories" / "bad_graph"
    graph_dir.mkdir(parents=True)
    (graph_dir / "config.json").write_text("[]", encoding="utf-8")

    runtime = backend.WebBackendFacade().core.graph_runtime

    try:
        runtime._read_graph_config("bad_graph")
    except GraphConfigReadError as exc:
        assert "JSON object" in str(exc)
    else:
        raise AssertionError("non-object graph config was not rejected")
