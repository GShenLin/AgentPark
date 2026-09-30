import base64
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.provider_auth import codex_oauth
from src.provider_auth.codex_credential_sync import sync_local_codex_credentials
from src.provider_auth.codex_oauth import CodexOAuthError
from src.provider_auth.store import get_account, list_accounts, save_account
from src.web_backend.provider_auth_api import ProviderAuthApiDomain
from src.web_backend.route_registry import ApiRouteRegistry


def jwt(claims):
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{encoded}.signature"


def auth(email="user@example.com", account_id="account-one", refresh="local-secret"):
    return {
        "auth_mode": "chatgpt",
        "tokens": {
            "id_token": jwt({"email": email, "https://api.openai.com/auth": {"chatgpt_account_id": account_id}}),
            "access_token": jwt({"exp": int(time.time()) + 3600}),
            "refresh_token": refresh,
            "account_id": account_id,
        },
        "last_refresh": "2026-09-28T00:00:00Z",
    }


@pytest.fixture
def local_store(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    monkeypatch.setattr("src.provider_auth.store.get_workspace_root", lambda: str(workspace))
    codex_home = tmp_path / "custom codex home"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setattr(codex_oauth, "_request_json", lambda *a, **kw: pytest.fail("must not refresh or call OpenAI"))
    path = codex_home / "auth.json"
    path.write_text(json.dumps(auth()), encoding="utf-8")
    return path


def test_sync_replaces_stale_credentials_without_modifying_codex(local_store):
    old = save_account("openai", kind="oauth", credential=auth(refresh="already-used"), identity="user@example.com", alias="Work")
    before = local_store.read_bytes()
    result = sync_local_codex_credentials(account_id=old.id)
    updated = get_account("openai", old.id)
    assert updated.credential["tokens"]["refresh_token"] == "local-secret"
    assert updated.alias == "Work"
    assert result == {"accountId": old.id, "sourcePath": str(local_store)}
    assert local_store.read_bytes() == before
    assert len(list_accounts("openai")) == 1


def test_sync_first_account_uses_custom_codex_home(local_store):
    result = sync_local_codex_credentials()
    assert get_account("openai").id == result["accountId"]
    assert get_account("openai").credential == json.loads(local_store.read_text(encoding="utf-8"))
    assert "local-secret" not in json.dumps(result)


def test_sync_defaults_to_backend_users_home(monkeypatch, local_store):
    monkeypatch.delenv("CODEX_HOME")
    home = local_store.parent / "backend-user"
    (home / ".codex").mkdir(parents=True)
    source = home / ".codex" / "auth.json"
    source.write_bytes(local_store.read_bytes())
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert sync_local_codex_credentials()["sourcePath"] == str(source)


def test_sync_pinned_account_does_not_switch_global_active_account(local_store):
    target = save_account("openai", kind="oauth", credential=auth(refresh="old"), identity="user@example.com")
    other = save_account("openai", kind="oauth", credential=auth("other@example.com", "other"), identity="other@example.com")
    sync_local_codex_credentials(account_id=target.id)
    assert get_account("openai").id == other.id
    assert get_account("openai", target.id).credential["tokens"]["refresh_token"] == "local-secret"


@pytest.mark.parametrize("email,account_id", [("other@example.com", "account-one"), ("user@example.com", "other-workspace")])
def test_mismatch_does_not_overwrite_or_add_an_account(local_store, email, account_id):
    old_payload = auth(email, account_id, "original-secret")
    old = save_account("openai", kind="oauth", credential=old_payload, identity=email)
    with pytest.raises(CodexOAuthError, match="不一致"):
        sync_local_codex_credentials(account_id=old.id)
    assert get_account("openai", old.id).credential == old_payload
    assert len(list_accounts("openai")) == 1


def test_workspace_id_alone_is_not_enough_to_match_users(local_store):
    payload = auth(email="")
    save_account("openai", kind="oauth", credential=payload, identity="account-one")
    local_store.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CodexOAuthError, match="不一致"):
        sync_local_codex_credentials()


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(auth_mode="apikey"),
    lambda d: d["tokens"].update(refresh_token={"secret": "not-a-string"}),
    lambda d: d["tokens"].update(access_token=jwt({"exp": int(time.time()) - 60})),
    lambda d: d["tokens"].update(access_token=jwt({"exp": "not-an-integer"})),
    lambda d: d["tokens"].update(account_id="wrong-account"),
    lambda d: d["tokens"].update(access_token=jwt({"exp": int(time.time()) + 3600, "https://api.openai.com/auth": {"chatgpt_account_id": "wrong"}})),
])
def test_invalid_source_preserves_existing_credentials(local_store, mutation):
    old_payload = auth(refresh="original-secret")
    old = save_account("openai", kind="oauth", credential=old_payload, identity="user@example.com")
    payload = auth()
    mutation(payload)
    local_store.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CodexOAuthError):
        sync_local_codex_credentials(account_id=old.id)
    assert get_account("openai", old.id).credential == old_payload


@pytest.mark.parametrize("mode", ["keyring", "auto", "ephemeral"])
def test_non_file_store_is_explicitly_rejected_even_with_stale_file(local_store, mode):
    (local_store.parent / "config.toml").write_text(f'cli_auth_credentials_store = "{mode}"', encoding="utf-8")
    with pytest.raises(CodexOAuthError, match="仅支持"):
        sync_local_codex_credentials()
    assert list_accounts("openai") == []


def test_missing_file_explains_which_device_is_read(local_store):
    local_store.unlink()
    with pytest.raises(CodexOAuthError, match="运行 AgentPark 服务的设备"):
        sync_local_codex_credentials()


def test_invalid_json_does_not_echo_secret(local_store):
    local_store.write_text('SECRET-INVALID-JSON', encoding="utf-8")
    with pytest.raises(CodexOAuthError) as caught:
        sync_local_codex_credentials()
    assert "SECRET-INVALID-JSON" not in str(caught.value)


def test_unknown_target_is_not_silently_created(local_store):
    with pytest.raises(CodexOAuthError, match="已不存在"):
        sync_local_codex_credentials(account_id="a" * 12)
    assert list_accounts("openai") == []


def test_sync_api_contract_and_secret_free_response(local_store):
    domain = ProviderAuthApiDomain(SimpleNamespace())
    app = FastAPI()
    method, path, resolver = next(route for route in ApiRouteRegistry.ROUTES if route[1].endswith("/codex/sync-local"))
    getattr(app, method)(path)(resolver(SimpleNamespace(provider_auth_api=domain)))
    with TestClient(app) as client:
        response = client.post(path, json={"accountId": None})
        assert response.status_code == 200
        result = response.json()
        assert result["status"]["authorized"] is True
        assert result["status"]["activeAccountId"] == result["accountId"]
        assert "local-secret" not in response.text
        assert "access_token" not in response.text
        assert client.post(path, json={"accountId": 123}).status_code == 422
        assert client.post(path, json={"sourcePath": "/arbitrary/file"}).status_code == 422
        local_store.unlink()
        failure = client.post(path, json={})
        assert failure.status_code == 409
        assert "未找到" in failure.json()["detail"]
