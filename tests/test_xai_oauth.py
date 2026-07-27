import base64
import json
import time

import pytest

from src.provider_auth import xai_oauth
from src.provider_auth.store import save_account


def _jwt(payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    return f"header.{encoded}.signature"


def test_xai_endpoint_allowlist_rejects_non_xai_hosts():
    with pytest.raises(xai_oauth.XaiOAuthError, match="outside"):
        xai_oauth._validate_endpoint("https://attacker.example/token")


def test_xai_refresh_updates_selected_account(monkeypatch, tmp_path):
    monkeypatch.setattr("src.provider_auth.store.get_workspace_root", lambda: str(tmp_path))
    account = save_account(
        "xai",
        kind="oauth",
        identity="user-1",
        credential={
            "accessToken": "expired",
            "refreshToken": "refresh-1",
            "expiresAt": int(time.time()) - 1,
            "identity": "user-1",
        },
    )
    monkeypatch.setattr(xai_oauth, "_discover", lambda: ("https://auth.x.ai/authorize", "https://auth.x.ai/token"))
    monkeypatch.setattr(
        xai_oauth,
        "_request_json",
        lambda *_args, **_kwargs: {
            "access_token": _jwt({"sub": "user-1", "email": "user@example.com"}),
            "refresh_token": "refresh-2",
            "expires_in": 3600,
        },
    )

    refreshed = xai_oauth.refresh_authorization(account_id=account.id)

    assert refreshed["refreshToken"] == "refresh-2"
    assert refreshed["identity"] == "user-1"
