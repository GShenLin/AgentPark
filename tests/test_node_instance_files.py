import json


def test_list_node_instance_files_returns_recursive_relative_paths(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths

    graph_id = "file_picker"
    node_id = "node1"
    runtime_root = tmp_path / "runtime"
    node_dir = runtime_root / "memories" / graph_id / node_id
    nested_dir = node_dir / "notes"
    nested_dir.mkdir(parents=True)
    (node_dir / "config.json").write_text(json.dumps({"node_id": node_id}), encoding="utf-8")
    (node_dir / "Soul.md").write_text("soul", encoding="utf-8")
    (nested_dir / "context.md").write_text("nested", encoding="utf-8")

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(runtime_root))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(runtime_root / "memories"))

    from fastapi.testclient import TestClient

    response = TestClient(backend.create_app()).get(
        f"/api/nodes/instances/{node_id}/files?graph_id={graph_id}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["graph_id"] == graph_id
    assert payload["node_id"] == node_id
    assert [item["path"] for item in payload["files"]] == ["config.json", "notes/context.md", "Soul.md"]
    assert all(not item["path"].startswith(str(runtime_root)) for item in payload["files"])


def test_list_node_instance_files_rejects_missing_node_directory(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import runtime_paths

    runtime_root = tmp_path / "runtime"
    (runtime_root / "memories").mkdir(parents=True)
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(runtime_root))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(runtime_root / "memories"))

    from fastapi.testclient import TestClient

    response = TestClient(backend.create_app()).get(
        "/api/nodes/instances/missing/files?graph_id=file_picker"
    )

    assert response.status_code == 404
