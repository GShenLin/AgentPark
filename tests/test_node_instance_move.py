import json
import os

from fastapi.testclient import TestClient


def _create_graph(client: TestClient, graph_id: str) -> None:
    response = client.post(
        f"/api/graphs/{graph_id}",
        json={"graph": {"id": graph_id, "name": graph_id, "output_routes": {}}},
    )
    assert response.status_code == 200


def _create_node(client: TestClient, graph_id: str, node_id: str, grid_x: int = 0) -> None:
    response = client.post(
        "/api/nodes/instances",
        json={
            "graph_id": graph_id,
            "node_id": node_id,
            "type_id": "append_node",
            "ui": {"grid_x": grid_x, "grid_y": 0},
        },
    )
    assert response.status_code == 200


def test_move_node_transfers_directory_identity_note_and_prunes_source_routes():
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    client = TestClient(backend.create_app())
    source_graph = "move_source"
    target_graph = "move_target"
    node_id = "Mover"
    _create_graph(client, source_graph)
    _create_graph(client, target_graph)
    _create_node(client, source_graph, node_id)
    _create_node(client, source_graph, "Peer", 1)
    _create_node(client, target_graph, "Occupied")

    saved = client.post(
        f"/api/graphs/{source_graph}",
        json={
            "graph": {
                "id": source_graph,
                "name": source_graph,
                "node_notes": {node_id: "keep this note"},
                "output_routes": {
                    node_id: [{"output_index": 0, "targets": [{"node_id": "Peer", "input_index": 0}]}],
                    "Peer": [{"output_index": 0, "targets": [{"node_id": node_id, "input_index": 0}]}],
                },
            }
        },
    )
    assert saved.status_code == 200

    moved = client.post(
        f"/api/nodes/instances/{node_id}/move?graph_id={source_graph}",
        json={"target_graph_id": target_graph},
    )

    assert moved.status_code == 200, moved.text
    payload = moved.json()
    assert payload["source_graph_id"] == source_graph
    assert payload["target_graph_id"] == target_graph
    assert payload["moved_node_note"] is True
    graphs_root = _get_graphs_dir()
    assert not os.path.exists(os.path.join(graphs_root, source_graph, node_id))
    target_node_path = os.path.join(graphs_root, target_graph, node_id, "config.json")
    assert os.path.isfile(target_node_path)
    target_node = json.loads(open(target_node_path, "r", encoding="utf-8").read())
    occupied_node = json.loads(
        open(os.path.join(graphs_root, target_graph, "Occupied", "config.json"), "r", encoding="utf-8").read()
    )
    assert target_node["graph_id"] == target_graph
    assert target_node["ui"] != occupied_node["ui"]

    source_config = json.loads(
        open(os.path.join(graphs_root, source_graph, "config.json"), "r", encoding="utf-8").read()
    )
    target_config = json.loads(
        open(os.path.join(graphs_root, target_graph, "config.json"), "r", encoding="utf-8").read()
    )
    assert node_id not in source_config["output_routes"]
    assert source_config["output_routes"]["Peer"][0]["targets"] == []
    assert node_id not in source_config["node_notes"]
    assert target_config["node_notes"][node_id] == "keep this note"

    source_nodes = client.get("/api/nodes/instances/configs", params={"graph_id": source_graph}).json()["node_ids"]
    target_nodes = client.get("/api/nodes/instances/configs", params={"graph_id": target_graph}).json()["node_ids"]
    assert node_id not in source_nodes
    assert node_id in target_nodes


def test_move_node_rejects_target_id_collision_without_changing_source():
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    client = TestClient(backend.create_app())
    source_graph = "move_collision_source"
    target_graph = "move_collision_target"
    _create_graph(client, source_graph)
    _create_graph(client, target_graph)
    _create_node(client, source_graph, "Same")
    _create_node(client, target_graph, "Same")

    response = client.post(
        f"/api/nodes/instances/Same/move?graph_id={source_graph}",
        json={"target_graph_id": target_graph},
    )

    assert response.status_code == 409
    assert os.path.isdir(os.path.join(_get_graphs_dir(), source_graph, "Same"))
    assert os.path.isdir(os.path.join(_get_graphs_dir(), target_graph, "Same"))


def test_move_node_rejects_working_node():
    import src.web_backend as backend

    client = TestClient(backend.create_app())
    source_graph = "move_busy_source"
    target_graph = "move_busy_target"
    _create_graph(client, source_graph)
    _create_graph(client, target_graph)
    _create_node(client, source_graph, "Busy")
    state = client.post(
        f"/api/nodes/instances/Busy/state?graph_id={source_graph}",
        json={"state": "working"},
    )
    assert state.status_code == 200

    response = client.post(
        f"/api/nodes/instances/Busy/move?graph_id={source_graph}",
        json={"target_graph_id": target_graph},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "node must be idle before it can be moved"


def test_move_node_rebinds_runtime_event_rules(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path / "runtime"))
    facade = backend.WebBackendFacade()
    client = TestClient(facade.build())
    source_graph = "move_events_source"
    target_graph = "move_events_target"
    node_id = "EventMover"
    _create_graph(client, source_graph)
    _create_graph(client, target_graph)
    _create_node(client, source_graph, node_id)
    source_rules = {
        "OnInput": [
            {
                "enabled": True,
                "action": "notice.write",
                "target": "builtin.runtime_event_notice",
                "params": {},
            }
        ]
    }
    facade.core.runtime_events.replace_source_event_rules(source_graph, node_id, source_rules)

    response = client.post(
        f"/api/nodes/instances/{node_id}/move?graph_id={source_graph}",
        json={"target_graph_id": target_graph},
    )

    assert response.status_code == 200, response.text
    assert response.json()["moved_event_handlers"] == 1
    assert facade.core.runtime_events.export_source_event_rules(source_graph, node_id) == {}
    assert facade.core.runtime_events.export_source_event_rules(target_graph, node_id) == source_rules


def test_move_node_rolls_back_directory_and_configs_when_graph_update_fails(monkeypatch):
    import src.web_backend as backend
    import src.web_backend.node_instance_move as move_module
    from src.web_backend.runtime_paths import _get_graphs_dir

    client = TestClient(backend.create_app())
    source_graph = "move_rollback_source"
    target_graph = "move_rollback_target"
    node_id = "RollbackMover"
    _create_graph(client, source_graph)
    _create_graph(client, target_graph)
    _create_node(client, source_graph, node_id)
    saved = client.post(
        f"/api/graphs/{source_graph}",
        json={
            "graph": {
                "id": source_graph,
                "name": source_graph,
                "node_notes": {node_id: "must survive rollback"},
                "output_routes": {node_id: [{"output_index": 0, "targets": []}]},
            }
        },
    )
    assert saved.status_code == 200

    target_config_path = os.path.normcase(
        os.path.join(_get_graphs_dir(), target_graph, "config.json")
    )
    original_write_graph_config = move_module.write_graph_config

    def fail_target_graph_write(path, payload):
        if os.path.normcase(path) == target_config_path:
            raise OSError("simulated target graph write failure")
        return original_write_graph_config(path, payload)

    monkeypatch.setattr(move_module, "write_graph_config", fail_target_graph_write)
    response = client.post(
        f"/api/nodes/instances/{node_id}/move?graph_id={source_graph}",
        json={"target_graph_id": target_graph},
    )

    assert response.status_code == 500
    graphs_root = _get_graphs_dir()
    source_node_path = os.path.join(graphs_root, source_graph, node_id, "config.json")
    assert os.path.isfile(source_node_path)
    assert not os.path.exists(os.path.join(graphs_root, target_graph, node_id))
    source_node = json.loads(open(source_node_path, "r", encoding="utf-8").read())
    source_config = json.loads(
        open(os.path.join(graphs_root, source_graph, "config.json"), "r", encoding="utf-8").read()
    )
    assert source_node["graph_id"] == source_graph
    assert source_config["node_notes"][node_id] == "must survive rollback"
    assert node_id in source_config["output_routes"]
    source_nodes = client.get("/api/nodes/instances/configs", params={"graph_id": source_graph}).json()["node_ids"]
    assert node_id in source_nodes
