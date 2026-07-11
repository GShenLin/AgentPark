import base64
import json
import time

from src.provider_auth import codex_oauth
from src.provider_auth.credentials import resolve_provider_request_credentials
from src.providers.openai_transport import OpenAITransport
from src.providers.openai_transport_errors import OpenAIHttpError


def _jwt(payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    return f"header.{encoded}.signature"


def _write_auth(tmp_path, *, expires_at):
    id_token = _jwt({
        "email": "user@example.com",
        "https://api.openai.com/auth": {
            "chatgpt_account_id": "account-123456",
            "chatgpt_plan_type": "plus",
        },
    })
    access_token = _jwt({"exp": expires_at})
    (tmp_path / "auth.json").write_text(json.dumps({
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": id_token,
            "access_token": access_token,
            "refresh_token": "refresh-token",
            "account_id": "account-123456",
        },
        "last_refresh": "2026-01-01T00:00:00Z",
    }), encoding="utf-8")
    return access_token


def test_codex_credentials_load_existing_auth_without_refresh(monkeypatch, tmp_path):
    access_token = _write_auth(tmp_path, expires_at=int(time.time()) + 3600)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(codex_oauth, "_request_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not refresh")))

    credentials = resolve_provider_request_credentials({"authMode": "codex"})

    assert credentials.base_url == "https://chatgpt.com/backend-api/codex"
    assert credentials.headers["Authorization"] == f"Bearer {access_token}"
    assert credentials.headers["ChatGPT-Account-ID"] == "account-123456"


def test_codex_credentials_refresh_expired_token_and_persist(monkeypatch, tmp_path):
    _write_auth(tmp_path, expires_at=int(time.time()) - 60)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    next_access_token = _jwt({"exp": int(time.time()) + 7200})
    monkeypatch.setattr(codex_oauth, "_request_json", lambda *_args, **_kwargs: {
        "access_token": next_access_token,
        "refresh_token": "next-refresh-token",
    })

    credentials = codex_oauth.refresh_authorization()
    persisted = json.loads((tmp_path / "auth.json").read_text(encoding="utf-8"))

    assert credentials.access_token == next_access_token
    assert persisted["tokens"]["refresh_token"] == "next-refresh-token"
    assert persisted["last_refresh"].endswith("Z")


def test_codex_status_never_returns_tokens(monkeypatch, tmp_path):
    _write_auth(tmp_path, expires_at=int(time.time()) + 3600)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))

    status = codex_oauth.authorization_status()

    assert status["authorized"] is True
    assert status["email"] == "user@example.com"
    assert status["accountIdSuffix"] == "123456"
    assert "access_token" not in status
    assert "refresh_token" not in status


def test_unauthorized_response_refreshes_once_even_when_retries_disabled():
    class Host:
        config = {"timeoutMs": 1000, "maxRetries": 0, "retryDelaySec": 0}

    host = Host()
    transport = OpenAITransport(host)
    attempts = []
    refreshed = []

    def post_once(**kwargs):
        attempts.append(dict(kwargs["headers"]))
        if len(attempts) == 1:
            raise OpenAIHttpError(401, "expired")
        return {"ok": True}

    def refresh_headers(headers):
        refreshed.append(True)
        headers["Authorization"] = "Bearer refreshed"
        return True

    host._curl_post_json_once = post_once
    host._refresh_responses_auth_headers = refresh_headers

    result = transport._post_json_with_retry(
        endpoint="responses",
        url="https://example.test/responses",
        headers={"Authorization": "Bearer expired"},
        payload_json="{}",
    )

    assert result == {"ok": True}
    assert refreshed == [True]
    assert len(attempts) == 2
    assert attempts[1]["Authorization"] == "Bearer refreshed"
