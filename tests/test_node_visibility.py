import json
import os

from fastapi.testclient import TestClient


def _write_json(path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _build_visibility_app(tmp_path, monkeypatch):
    import src.web_backend as backend
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    graph_dir = graphs_dir / "work"
    _write_json(
        graph_dir / "config.json",
        {
            "id": "work",
            "name": "Work",
            "output_routes": {
                "public": [
                    {
                        "output_index": 0,
                        "targets": [
                            {"node_id": "secret", "input_index": 0},
                            {"node_id": "other", "input_index": 0},
                        ],
                    }
                ],
                "secret": [
                    {
                        "output_index": 0,
                        "targets": [{"node_id": "other", "input_index": 0}],
                    }
                ],
            },
        },
    )
    for node_id, private in (("public", False), ("secret", True), ("other", False)):
        _write_json(
            graph_dir / node_id / "config.json",
            {
                "node_id": node_id,
                "graph_id": "work",
                "type_id": "basic_trigger_node",
                "name": node_id.title(),
                "private": private,
                "state": "idle",
            },
        )
        (graph_dir / node_id / "memory.md").write_text(f"memory:{node_id}", encoding="utf-8")

    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    return backend.create_app(), graph_dir


def test_private_node_is_hidden_from_external_clients(tmp_path, monkeypatch):
    app, _graph_dir = _build_visibility_app(tmp_path, monkeypatch)
    local = TestClient(app, client=("127.0.0.1", 12345))
    remote = TestClient(app, client=("10.0.0.9", 12345))

    local_nodes = {
        item["node_id"]: item
        for item in local.get("/api/nodes/instances/configs", params={"graph_id": "work"}).json()["nodes"]
    }
    assert set(local_nodes) == {"public", "secret", "other"}
    assert local_nodes["secret"]["private"] is True

    remote_nodes = {
        item["node_id"]: item
        for item in remote.get("/api/nodes/instances/configs", params={"graph_id": "work"}).json()["nodes"]
    }
    assert set(remote_nodes) == {"public", "other"}
    assert remote.get(
        "/api/nodes/instances/secret/memory",
        params={"graph_id": "work"},
    ).status_code == 404
    assert remote.post(
        "/api/nodes/run",
        json={
            "node_id": "basic_trigger_node",
            "input": "hidden",
            "context": {"graph_id": "work", "node_instance_id": "secret"},
        },
    ).status_code == 404
    assert remote.post(
        "/api/nodes/run_async",
        json={
            "node_id": "basic_trigger_node",
            "input": "hidden",
            "context": {"graph_id": "work", "node_instance_id": "secret"},
        },
    ).status_code == 404
    assert remote.get(
        "/api/mobile/pcs/local/graphs/work/nodes/secret/conversation",
    ).status_code == 404
    mobile_ids = {
        item["id"]
        for item in remote.get("/api/mobile/pcs/local/graphs/work/nodes").json()["nodes"]
    }
    assert mobile_ids == {"public", "other"}
    assert remote.get("/memories/work/secret/memory.md").status_code == 404
    assert local.get("/memories/work/secret/memory.md").text == "memory:secret"

    remote_graph = remote.get("/api/graphs/work").json()["graph"]
    assert "secret" not in remote_graph["output_routes"]
    public_targets = remote_graph["output_routes"]["public"][0]["targets"]
    assert public_targets == [{"node_id": "other", "input_index": 0}]


def test_visibility_lookup_does_not_materialize_node_runtime_state(tmp_path, monkeypatch):
    app, _graph_dir = _build_visibility_app(tmp_path, monkeypatch)
    from src.web_backend.runtime_state_memory_store import runtime_state_memory_store

    original_snapshot = runtime_state_memory_store.snapshot
    snapshot_paths = []

    def record_runtime_snapshot(config_path):
        snapshot_paths.append(config_path)
        return original_snapshot(config_path)

    monkeypatch.setattr(runtime_state_memory_store, "snapshot", record_runtime_snapshot)
    local = TestClient(app, client=("127.0.0.1", 12345))

    response = local.get(
        "/api/nodes/instances/public/memory",
        params={"graph_id": "work"},
    )

    assert response.status_code == 200
    assert len(snapshot_paths) == 1
    assert snapshot_paths[0].endswith(os.path.join("public", "config.json"))


def test_node_visibility_can_only_be_changed_locally(tmp_path, monkeypatch):
    app, _graph_dir = _build_visibility_app(tmp_path, monkeypatch)
    local = TestClient(app, client=("127.0.0.1", 12345))
    remote = TestClient(app, client=("10.0.0.9", 12345))

    denied = remote.patch(
        "/api/nodes/instances/public/visibility",
        params={"graph_id": "work"},
        json={"private": True},
    )
    assert denied.status_code == 403

    invalid = local.patch(
        "/api/nodes/instances/public/visibility",
        params={"graph_id": "work"},
        json={"private": "true"},
    )
    assert invalid.status_code == 400

    changed = local.patch(
        "/api/nodes/instances/public/visibility",
        params={"graph_id": "work"},
        json={"private": True},
    )
    assert changed.status_code == 200
    assert changed.json()["private"] is True
    remote_ids = remote.get(
        "/api/nodes/instances/configs",
        params={"graph_id": "work"},
    ).json()["node_ids"]
    assert "public" not in remote_ids


def test_remote_graph_save_preserves_routes_hidden_by_private_nodes(tmp_path, monkeypatch):
    app, graph_dir = _build_visibility_app(tmp_path, monkeypatch)
    remote = TestClient(app, client=("10.0.0.9", 12345))

    response = remote.post(
        "/api/graphs/work",
        json={
            "graph": {
                "id": "work",
                "name": "Work remote edit",
                "output_routes": {
                    "public": [
                        {
                            "output_index": 0,
                            "targets": [{"node_id": "other", "input_index": 0}],
                        }
                    ]
                },
            }
        },
    )
    assert response.status_code == 200

    stored = json.loads((graph_dir / "config.json").read_text(encoding="utf-8"))
    assert "secret" in stored["output_routes"]
    public_targets = stored["output_routes"]["public"][0]["targets"]
    assert {target["node_id"] for target in public_targets} == {"secret", "other"}
