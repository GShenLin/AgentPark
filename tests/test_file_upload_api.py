from pathlib import Path


def test_file_upload_endpoint_persists_files_and_returns_resource_metadata(tmp_path):
    import src.web_backend as backend

    runtime_root = str(tmp_path)
    original_get_runtime_root = backend._get_runtime_root
    original_get_resource_root = backend._get_resource_root
    resource_root = original_get_runtime_root()
    import src.web_backend.system_file_api as system_file_api
    original_get_graphs_dir = system_file_api._get_graphs_dir

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root
    system_file_api._get_graphs_dir = lambda: str(tmp_path / "memories")

    try:
        app = backend.create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.post(
            "/api/files/upload",
            data={"trace_id": "composer-drop"},
            files=[
                ("files", ("scene.png", b"fake-png", "image/png")),
                ("files", ("notes.txt", b"hello", "text/plain")),
            ],
        )
        assert response.status_code == 200

        payload = response.json() or {}
        assert payload.get("trace_id") == "composer-drop"
        files = payload.get("files")
        assert isinstance(files, list)
        assert len(files) == 2

        image_item = next((item for item in files if str(item.get("name") or "") == "scene.png"), None)
        assert isinstance(image_item, dict)
        assert image_item.get("kind") == "image"
        assert image_item.get("mime") == "image/png"
        assert image_item.get("source") == "web_upload"
        assert Path(str(image_item.get("path") or "")).is_file()

        text_item = next((item for item in files if str(item.get("name") or "") == "notes.txt"), None)
        assert isinstance(text_item, dict)
        assert text_item.get("kind") == "doc"
        assert text_item.get("mime") == "text/plain"
        assert Path(str(text_item.get("path") or "")).read_text(encoding="utf-8") == "hello"
    finally:
        backend._get_runtime_root = original_get_runtime_root
        backend._get_resource_root = original_get_resource_root
        system_file_api._get_graphs_dir = original_get_graphs_dir
