import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.web_backend.remote_api import RemoteApiDomain


def _request_from(host: str):
    return SimpleNamespace(client=SimpleNamespace(host=host))


def _write_remote_config(tmp_path, remotes):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "remote.json").write_text(
        json.dumps({"remotes": remotes}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_remote_api_hides_private_remotes_for_nonlocal_clients(monkeypatch, tmp_path):
    import src.web_backend.remote_api as remote_api_module

    monkeypatch.setattr(remote_api_module, "_get_runtime_root", lambda: str(tmp_path))
    _write_remote_config(
        tmp_path,
        [
            {"id": "public", "name": "Public", "host": "10.0.0.2", "port": 8788},
            {"id": "secret", "name": "Secret", "host": "10.0.0.3", "port": 8788, "private": True},
        ],
    )
    domain = RemoteApiDomain(SimpleNamespace())

    remote_view = domain.list_remotes(_request_from("10.0.0.9"))
    assert [item["id"] for item in remote_view["remotes"]] == ["default", "public"]

    local_view = domain.list_remotes(_request_from("127.0.0.1"))
    assert [item["id"] for item in local_view["remotes"]] == ["default", "public", "secret"]
    assert local_view["remotes"][2]["private"] is True


def test_remote_api_route_uses_request_client_address(monkeypatch, tmp_path):
    import src.web_backend.remote_api as remote_api_module
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setattr(remote_api_module, "_get_runtime_root", lambda: str(tmp_path))
    _write_remote_config(
        tmp_path,
        [{"id": "secret", "name": "Secret", "host": "10.0.0.3", "port": 8788, "private": True}],
    )
    domain = RemoteApiDomain(SimpleNamespace())
    app = FastAPI()
    app.get("/api/remotes")(domain.list_remotes)

    response = TestClient(app, client=("10.0.0.9", 12345)).get("/api/remotes")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["remotes"]] == ["default"]


def test_remote_status_reports_whether_client_is_local(monkeypatch, tmp_path):
    import src.web_backend.remote_api as remote_api_module

    monkeypatch.setattr(remote_api_module, "_get_runtime_root", lambda: str(tmp_path))
    domain = RemoteApiDomain(SimpleNamespace())

    assert domain.get_remote_status(_request_from("127.0.0.1")) == {"is_local_client": True}
    assert domain.get_remote_status(_request_from("10.0.0.9")) == {"is_local_client": False}


def test_remote_api_rejects_private_remote_created_from_nonlocal_client(monkeypatch, tmp_path):
    import src.web_backend.remote_api as remote_api_module

    monkeypatch.setattr(remote_api_module, "_get_runtime_root", lambda: str(tmp_path))
    domain = RemoteApiDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        domain.add_remote(
            {"name": "Secret", "host": "10.0.0.3", "port": 8788, "private": True},
            _request_from("10.0.0.9"),
        )

    assert exc.value.status_code == 403


def test_remote_api_does_not_delete_private_remotes_from_nonlocal_clients(monkeypatch, tmp_path):
    import src.web_backend.remote_api as remote_api_module

    monkeypatch.setattr(remote_api_module, "_get_runtime_root", lambda: str(tmp_path))
    _write_remote_config(
        tmp_path,
        [{"id": "secret", "name": "Secret", "host": "10.0.0.3", "port": 8788, "private": True}],
    )
    domain = RemoteApiDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        domain.delete_remote("secret", _request_from("10.0.0.9"))

    assert exc.value.status_code == 404
    local_view = domain.list_remotes(_request_from("127.0.0.1"))
    assert [item["id"] for item in local_view["remotes"]] == ["default", "secret"]


def test_remote_api_requires_private_to_be_boolean(monkeypatch, tmp_path):
    import src.web_backend.remote_api as remote_api_module

    monkeypatch.setattr(remote_api_module, "_get_runtime_root", lambda: str(tmp_path))
    domain = RemoteApiDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        domain.add_remote({"name": "Secret", "host": "10.0.0.3", "port": 8788, "private": "true"})

    assert exc.value.status_code == 400
    assert "private" in str(exc.value.detail)
