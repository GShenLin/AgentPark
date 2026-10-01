import json

import pytest
from fastapi import HTTPException

from src.remote_workspace.directories import list_directories
from src.web_backend.remote_workspace_api import RemoteWorkspaceApiDomain


def test_listing_uses_target_paths_and_reports_invalid_paths(tmp_path):
    (tmp_path / "nested").mkdir()
    (tmp_path / "file.txt").write_text("not a directory")
    listing = json.loads(list_directories({}, str(tmp_path)))
    assert listing["current_path"] == str(tmp_path)
    assert listing["parent_path"] == str(tmp_path.parent)
    assert listing["files"] == [{"name": "nested", "path": str(tmp_path / "nested"), "type": "dir"}]
    assert listing["roots"]
    with pytest.raises(ValueError, match="absolute"):
        list_directories({"path": "relative"}, str(tmp_path))
    with pytest.raises(ValueError, match="does not exist"):
        list_directories({"path": str(tmp_path / "missing")}, str(tmp_path))


def test_directory_api_routes_to_selected_worker_without_native_picker(monkeypatch, tmp_path):
    api = RemoteWorkspaceApiDomain()
    worker = {"workspace_path": str(tmp_path), "capabilities": ["list_directories"]}
    monkeypatch.setattr(api, "_wait_online", lambda identity, timeout: worker)
    def execute(payload):
        assert payload["worker_id"] == "selected-remote"
        assert payload["tool_name"] == "list_directories"
        return list_directories(payload["arguments"], payload["working_path"])
    monkeypatch.setattr(api, "_execute", execute)
    assert api.list_worker_directories({"worker_id": "selected-remote", "path": ""})["current_path"] == str(tmp_path)
    worker["capabilities"] = ["select_folder"]
    with pytest.raises(HTTPException, match="更新"):
        api.list_worker_directories({"worker_id": "selected-remote", "path": ""})
