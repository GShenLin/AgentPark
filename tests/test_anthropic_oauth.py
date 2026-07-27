import time

import pytest

from src.provider_auth import anthropic_oauth
from src.provider_auth.store import get_account, save_account


def test_anthropic_refresh_updates_selected_account(monkeypatch, tmp_path):
    monkeypatch.setattr("src.provider_auth.store.get_workspace_root", lambda: str(tmp_path))
    account = save_account(
        "anthropic",
        kind="oauth",
        identity="account-1",
        credential={
            "accessToken": "expired",
            "refreshToken": "refresh-1",
            "expiresAt": int(time.time()) - 1,
            "identity": "account-1",
        },
    )
    monkeypatch.setattr(
        anthropic_oauth,
        "_post_token",
        lambda payload: {
            "access_token": "access-2",
            "refresh_token": "refresh-2",
            "expires_in": 3600,
            "account": {"uuid": "account-1", "email_address": "user@example.com"},
        },
    )

    refreshed = anthropic_oauth.refresh_authorization(account_id=account.id)

    assert refreshed["accessToken"] == "access-2"
    assert get_account("anthropic", account.id).credential["refreshToken"] == "refresh-2"


def test_anthropic_token_requires_stable_identity():
    with pytest.raises(anthropic_oauth.AnthropicOAuthError, match="identity"):
        anthropic_oauth._normalize({
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
        })


def test_anthropic_manual_code_flow_persists_account(monkeypatch, tmp_path):
    monkeypatch.setattr("src.provider_auth.store.get_workspace_root", lambda: str(tmp_path))

    class FakeServer:
        RequestHandlerClass = None

        def serve_forever(self):
            return

        def shutdown(self):
            return

    manager = anthropic_oauth.AnthropicLoginManager()
    monkeypatch.setattr(manager, "_bind_server", lambda: FakeServer())
    monkeypatch.setattr(
        anthropic_oauth,
        "_post_token",
        lambda payload: {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
            "account": {"uuid": "claude-account", "email_address": "claude@example.com"},
        },
    )

    started = manager.start()
    state = manager._session["state"]
    manager.submit_code(f"authorization-code#{state}")

    assert started["manualCode"] is True
    assert "code_challenge=" in started["authUrl"]
    assert get_account("anthropic").identity == "claude-account"
