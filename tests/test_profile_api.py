import json
import os
import shutil
import uuid


def _patch_profile_root(monkeypatch, tmp_path):
    from src.web_backend import profile_storage

    monkeypatch.setattr(profile_storage, "get_workspace_root", lambda: str(tmp_path))


def test_agent_profile_from_node_upserts_and_strips_runtime_fields(tmp_path, monkeypatch):
    _patch_profile_root(monkeypatch, tmp_path)

    import src.web_backend as backend
    from fastapi.testclient import TestClient
    from src.web_backend.node_config_service import node_config_service
    from src.web_backend.runtime_paths import _get_graphs_dir

    graph_id = f"ut_profile_agent_{uuid.uuid4().hex[:8]}"
    node_id = "agent_profile_node"
    profile_id = "agent-default"
    graph_dir = os.path.join(_get_graphs_dir(), graph_id)

    try:
        client = TestClient(backend.create_app())
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": graph_id, "ui": {"x": 1, "y": 2}},
        )
        assert created.status_code == 200

        config_path = os.path.join(graph_dir, node_id, "config.json")
        cfg = node_config_service.read_strict(config_path)
        cfg.update(
            {
                "prefix": "hello",
                "state": "working",
                "pending": [{"payload": "queued"}],
                "last_message": "runtime preview",
                "runtime_events": [{"type": "runtime_notice"}],
            }
        )
        node_config_service.write(config_path, cfg)

        first = client.post(
            "/api/profiles/agents/from-node",
            json={
                "graph_id": graph_id,
                "node_id": node_id,
                "profile_id": profile_id,
                "profile_name": "Agent Default",
            },
        )
        assert first.status_code == 200
        second = client.post(
            "/api/profiles/agents/from-node",
            json={
                "graph_id": graph_id,
                "node_id": node_id,
                "profile_id": profile_id,
                "profile_name": "Agent Default Updated",
            },
        )
        assert second.status_code == 200

        profile_path = tmp_path / "config" / "agentProfile.json"
        payload = json.loads(profile_path.read_text(encoding="utf-8"))
        profiles = payload["profiles"]
        assert len([item for item in profiles if item["id"] == profile_id]) == 1
        saved = next(item for item in profiles if item["id"] == profile_id)
        assert saved["name"] == "Agent Default Updated"
        assert saved["node_type_id"] == "append_node"
        assert saved["fields"]["prefix"] == "hello"
        assert "state" not in saved["fields"]
        assert "pending" not in saved["fields"]
        assert "last_message" not in saved["fields"]
        assert "runtime_events" not in saved["fields"]
    finally:
        shutil.rmtree(graph_dir, ignore_errors=True)


def test_graph_profile_create_retargets_graph_and_node_config_ids(tmp_path, monkeypatch):
    _patch_profile_root(monkeypatch, tmp_path)

    import src.web_backend as backend
    from fastapi.testclient import TestClient
    from src.web_backend.node_config_service import node_config_service, node_runtime_state_path
    from src.web_backend.runtime_paths import _get_graphs_dir

    source_graph_id = f"ut_profile_src_{uuid.uuid4().hex[:8]}"
    target_graph_id = f"ut_profile_dst_{uuid.uuid4().hex[:8]}"
    node_id = "profile_graph_node"
    profile_id = "research-flow"
    graphs_dir = _get_graphs_dir()
    source_dir = os.path.join(graphs_dir, source_graph_id)
    target_dir = os.path.join(graphs_dir, target_graph_id)

    try:
        client = TestClient(backend.create_app())
        created = client.post(
            "/api/nodes/instances",
            json={"node_id": node_id, "type_id": "append_node", "graph_id": source_graph_id, "ui": {"x": 11, "y": 22}},
        )
        assert created.status_code == 200
        saved_graph = client.post(
            f"/api/graphs/{source_graph_id}",
            json={
                "graph": {
                    "id": source_graph_id,
                    "name": source_graph_id,
                    "nodes": [],
                    "links": [{"id": "l1", "from": {"node": node_id, "index": 0}, "to": {"node": node_id, "index": 0}}],
                }
            },
        )
        assert saved_graph.status_code == 200

        config_path = os.path.join(source_dir, node_id, "config.json")
        cfg = node_config_service.read_strict(config_path)
        cfg.update(
            {
                "suffix": "world",
                "state": "working",
                "pending": [{"payload": "queued"}],
                "last_message": "runtime preview",
                "runtime_tool_calls": [{"name": "tool"}],
            }
        )
        node_config_service.write(config_path, cfg)

        saved_profile = client.post(
            "/api/profiles/graphs/from-graph",
            json={"graph_id": source_graph_id, "profile_id": profile_id, "profile_name": "Research Flow"},
        )
        assert saved_profile.status_code == 200

        created_graph = client.post(f"/api/profiles/graphs/{profile_id}/create", json={"graph_id": target_graph_id})
        assert created_graph.status_code == 200

        graph_config = json.loads(open(os.path.join(target_dir, "config.json"), "r", encoding="utf-8").read())
        assert graph_config["id"] == target_graph_id
        assert graph_config["name"] == target_graph_id

        node_config_path = os.path.join(target_dir, node_id, "config.json")
        target_cfg = json.loads(open(node_config_path, "r", encoding="utf-8").read())
        assert target_cfg["node_id"] == node_id
        assert target_cfg["graph_id"] == target_graph_id
        assert target_cfg["type_id"] == "append_node"
        assert target_cfg["suffix"] == "world"
        for runtime_key in ("state", "pending", "last_message", "runtime_tool_calls"):
            assert runtime_key not in target_cfg
        runtime_state_path = node_runtime_state_path(node_config_path)
        if os.path.exists(runtime_state_path):
            assert json.loads(open(runtime_state_path, "r", encoding="utf-8").read()) == {}
        assert not os.path.exists(os.path.join(target_dir, node_id, "memory.md"))
        assert not os.path.exists(os.path.join(target_dir, node_id, "messages.jsonl"))

        profile_file = json.loads((tmp_path / "config" / "graphProfile.json").read_text(encoding="utf-8"))
        profile = next(item for item in profile_file["profiles"] if item["id"] == profile_id)
        assert profile["graph"]["id"] == source_graph_id
        assert profile["node_configs"][0]["graph_id"] == source_graph_id
        assert profile["node_configs"][0]["fields"]["suffix"] == "world"
        assert "pending" not in profile["node_configs"][0]["fields"]
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)
        shutil.rmtree(target_dir, ignore_errors=True)


def test_graph_profile_create_rejects_existing_graph_id(tmp_path, monkeypatch):
    _patch_profile_root(monkeypatch, tmp_path)

    import src.web_backend as backend
    from fastapi.testclient import TestClient
    from src.web_backend.runtime_paths import _get_graphs_dir

    source_graph_id = f"ut_profile_exists_src_{uuid.uuid4().hex[:8]}"
    target_graph_id = f"ut_profile_exists_dst_{uuid.uuid4().hex[:8]}"
    profile_id = "existing-target"
    graphs_dir = _get_graphs_dir()
    source_dir = os.path.join(graphs_dir, source_graph_id)
    target_dir = os.path.join(graphs_dir, target_graph_id)

    try:
        client = TestClient(backend.create_app())
        assert client.post("/api/nodes/instances", json={"node_id": "n1", "type_id": "append_node", "graph_id": source_graph_id}).status_code == 200
        assert client.post("/api/nodes/instances", json={"node_id": "n2", "type_id": "append_node", "graph_id": target_graph_id}).status_code == 200
        assert client.post(
            "/api/profiles/graphs/from-graph",
            json={"graph_id": source_graph_id, "profile_id": profile_id, "profile_name": "Existing Target"},
        ).status_code == 200

        response = client.post(f"/api/profiles/graphs/{profile_id}/create", json={"graph_id": target_graph_id})

        assert response.status_code == 409
        assert "already exists" in response.json().get("detail", "")
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)
        shutil.rmtree(target_dir, ignore_errors=True)

