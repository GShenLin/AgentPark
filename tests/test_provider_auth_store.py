import json
from pathlib import Path

from src.config_loader import ConfigLoader
from src.provider_auth.credentials import resolve_provider_request_credentials
from src.provider_auth.service import add_api_key_account
from src.provider_auth.store import (
    get_account,
    list_accounts,
    remove_account,
    save_account,
    set_active_account,
)


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr("src.provider_auth.store.get_workspace_root", lambda: str(tmp_path))


def test_provider_accounts_are_separated_and_switchable(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    first = save_account("kimi", kind="oauth", credential={"accessToken": "first"}, identity="first@example.com")
    second = save_account("kimi", kind="oauth", credential={"accessToken": "second"}, identity="second@example.com")

    assert get_account("kimi").id == second.id
    assert set_active_account("kimi", first.id) is True
    assert get_account("kimi").credential["accessToken"] == "first"
    assert len(list_accounts("kimi")) == 2
    assert (tmp_path / ".auth" / "kimi" / "accounts" / f"{first.id}.json").is_file()


def test_removing_active_account_promotes_remaining_account(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    first = save_account("deepseek", kind="api_key", credential={"apiKey": "one"}, identity="one")
    second = save_account("deepseek", kind="api_key", credential={"apiKey": "two"}, identity="two")

    assert remove_account("deepseek", second.id) is True
    assert get_account("deepseek").id == first.id


def test_api_key_accounts_drive_runtime_credentials(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    add_api_key_account("deepseek", api_key="secret-one", identity="team-one")
    add_api_key_account("deepseek", api_key="secret-two", identity="team-two")
    first_id = next(item["id"] for item in list_accounts("deepseek") if item["identity"] == "team-one")

    assert set_active_account("deepseek", first_id)
    credentials = resolve_provider_request_credentials(
        {"authMode": "api_key", "authProvider": "deepseek", "baseUrl": "https://api.deepseek.com"}
    )
    assert credentials.headers == {"Authorization": "Bearer secret-one"}


def test_account_indexes_never_contain_secrets(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    save_account("xai", kind="api_key", credential={"apiKey": "super-secret"}, identity="work")

    index = json.loads((tmp_path / ".auth" / "xai" / "accounts.json").read_text(encoding="utf-8"))
    assert "super-secret" not in json.dumps(index)


def test_config_loader_resolves_provider_pinned_api_key_account(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    first = save_account("deepseek", kind="api_key", credential={"apiKey": "first-key"}, identity="first")
    second = save_account("deepseek", kind="api_key", credential={"apiKey": "second-key"}, identity="second")
    config_path = Path(tmp_path, "modelProvider.json")
    config_path.write_text(json.dumps({
        "providers": {
            "pinned": {
                "type": "deepseek",
                "model": "deepseek-chat",
                "baseUrl": "https://api.deepseek.com",
                "authMode": "api_key",
                "authProvider": "deepseek",
                "authAccountId": first.id,
                "supportmode": ["chat"],
            }
        }
    }), encoding="utf-8")
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))

    provider = ConfigLoader().get_provider_config("pinned")

    assert provider["apiKey"] == "first-key"
    assert provider["authAccountId"] == first.id
    assert get_account("deepseek").id == second.id
