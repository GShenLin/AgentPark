import json
import os


def test_node_folder_routes_open_distinct_directories(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import node_instance_registry, runtime_paths

    graph_id = "folder_routes"
    node_id = "node1"
    runtime_root = tmp_path / "runtime"
    node_dir = runtime_root / "memories" / graph_id / node_id
    work_dir = tmp_path / "work"
    node_dir.mkdir(parents=True)
    work_dir.mkdir()
    (node_dir / "config.json").write_text(
        json.dumps({"node_id": node_id, "working_path": str(work_dir)}, ensure_ascii=False),
        encoding="utf-8",
    )

    opened_paths: list[str] = []

    def record_open(target_dir):
        opened_paths.append(os.path.normpath(target_dir))

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(runtime_root))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(runtime_root / "memories"))
    monkeypatch.setattr(node_instance_registry.os, "name", "nt")
    monkeypatch.setattr(node_instance_registry.NodeInstanceRegistry, "_launch_folder_explorer", staticmethod(record_open))

    from fastapi.testclient import TestClient

    client = TestClient(backend.create_app())
    node_response = client.post(f"/api/nodes/instances/{node_id}/open-node-folder?graph_id={graph_id}")
    work_response = client.post(f"/api/nodes/instances/{node_id}/open-work-folder?graph_id={graph_id}")

    assert node_response.status_code == 200
    assert node_response.json()["source"] == "node_folder"
    assert os.path.normpath(node_response.json()["path"]) == os.path.normpath(str(node_dir))
    assert work_response.status_code == 200
    assert work_response.json()["source"] == "work_folder"
    assert os.path.normpath(work_response.json()["path"]) == os.path.normpath(str(work_dir))
    assert opened_paths == [os.path.normpath(str(node_dir)), os.path.normpath(str(work_dir))]


def test_open_work_folder_uses_graph_working_path_when_node_path_is_empty(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import node_instance_registry, runtime_paths

    graph_id = "graph_work_folder"
    node_id = "node1"
    runtime_root = tmp_path / "runtime"
    graph_dir = runtime_root / "memories" / graph_id
    node_dir = graph_dir / node_id
    graph_work_dir = tmp_path / "graph-work"
    node_dir.mkdir(parents=True)
    graph_work_dir.mkdir()
    (graph_dir / "config.json").write_text(
        json.dumps({"id": graph_id, "working_path": str(graph_work_dir)}),
        encoding="utf-8",
    )
    (node_dir / "config.json").write_text(
        json.dumps({"node_id": node_id, "working_path": ""}),
        encoding="utf-8",
    )

    opened_paths: list[str] = []

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(runtime_root))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(runtime_root / "memories"))
    monkeypatch.setattr(node_instance_registry.os, "name", "nt")
    monkeypatch.setattr(
        node_instance_registry.NodeInstanceRegistry,
        "_launch_folder_explorer",
        staticmethod(lambda target_dir: opened_paths.append(os.path.normpath(target_dir))),
    )

    from fastapi.testclient import TestClient

    response = TestClient(backend.create_app()).post(
        f"/api/nodes/instances/{node_id}/open-work-folder?graph_id={graph_id}"
    )

    assert response.status_code == 200
    assert os.path.normpath(response.json()["path"]) == os.path.normpath(str(graph_work_dir))
    assert opened_paths == [os.path.normpath(str(graph_work_dir))]


def test_open_work_folder_uses_project_folder_when_node_and_graph_paths_are_empty(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.providers import agent_environment_context
    from src.web_backend import node_instance_registry, runtime_paths

    graph_id = "project_work_folder"
    node_id = "node1"
    project_dir = tmp_path / "project"
    graph_dir = project_dir / "memories" / graph_id
    node_dir = graph_dir / node_id
    node_dir.mkdir(parents=True)
    (graph_dir / "config.json").write_text(
        json.dumps({"id": graph_id, "working_path": ""}),
        encoding="utf-8",
    )
    (node_dir / "config.json").write_text(
        json.dumps({"node_id": node_id, "working_path": ""}),
        encoding="utf-8",
    )

    opened_paths: list[str] = []

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(project_dir))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(project_dir / "memories"))
    monkeypatch.setattr(agent_environment_context, "get_workspace_root", lambda: str(project_dir))
    monkeypatch.setattr(node_instance_registry.os, "name", "nt")
    monkeypatch.setattr(
        node_instance_registry.NodeInstanceRegistry,
        "_launch_folder_explorer",
        staticmethod(lambda target_dir: opened_paths.append(os.path.normpath(target_dir))),
    )

    from fastapi.testclient import TestClient

    response = TestClient(backend.create_app()).post(
        f"/api/nodes/instances/{node_id}/open-work-folder?graph_id={graph_id}"
    )

    assert response.status_code == 200
    assert os.path.normpath(response.json()["path"]) == os.path.normpath(str(project_dir))
    assert opened_paths == [os.path.normpath(str(project_dir))]
