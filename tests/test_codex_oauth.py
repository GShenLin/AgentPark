import base64
import json
import time

from src.provider_auth import codex_oauth
from src.provider_auth.credentials import ProviderRequestCredentials
from src.provider_auth.credentials import resolve_provider_request_credentials
from src.provider_auth.store import get_account, save_account
from src.providers.openai_transport import OpenAITransport
from src.providers.openai_transport_errors import OpenAIHttpError
from src.providers.responses_runtime_methods import ResponsesRuntimeMethods


def _jwt(payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    return f"header.{encoded}.signature"


def _write_auth(monkeypatch, tmp_path, *, expires_at, email="user@example.com", account_id="account-123456"):
    monkeypatch.setattr("src.provider_auth.store.get_workspace_root", lambda: str(tmp_path))
    id_token = _jwt({
        "email": email,
        "https://api.openai.com/auth": {
            "chatgpt_account_id": account_id,
            "chatgpt_plan_type": "plus",
        },
    })
    access_token = _jwt({"exp": expires_at})
    payload = {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": id_token,
            "access_token": access_token,
            "refresh_token": "refresh-token",
            "account_id": account_id,
        },
        "last_refresh": "2026-01-01T00:00:00Z",
    }
    save_account("openai", kind="oauth", credential=payload, identity=email)
    return access_token


def test_codex_credentials_load_existing_auth_without_refresh(monkeypatch, tmp_path):
    access_token = _write_auth(monkeypatch, tmp_path, expires_at=int(time.time()) + 3600)
    monkeypatch.setattr(codex_oauth, "_request_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not refresh")))

    credentials = resolve_provider_request_credentials({"authMode": "codex"})

    assert credentials.base_url == "https://chatgpt.com/backend-api/codex"
    assert credentials.headers["Authorization"] == f"Bearer {access_token}"
    assert credentials.headers["ChatGPT-Account-ID"] == "account-123456"
    assert credentials.headers["originator"] == "codex_cli_rs"
    assert credentials.headers["User-Agent"] == "codex_cli_rs/0.0.0 (Windows; x86_64) AgentPark"


def test_codex_credentials_refresh_expired_token_and_persist(monkeypatch, tmp_path):
    _write_auth(monkeypatch, tmp_path, expires_at=int(time.time()) - 60)
    next_access_token = _jwt({"exp": int(time.time()) + 7200})
    monkeypatch.setattr(codex_oauth, "_request_json", lambda *_args, **_kwargs: {
        "access_token": next_access_token,
        "refresh_token": "next-refresh-token",
    })

    credentials = codex_oauth.refresh_authorization()
    persisted = get_account("openai").credential

    assert credentials.access_token == next_access_token
    assert persisted["tokens"]["refresh_token"] == "next-refresh-token"
    assert persisted["last_refresh"].endswith("Z")


def test_codex_status_never_returns_tokens(monkeypatch, tmp_path):
    _write_auth(monkeypatch, tmp_path, expires_at=int(time.time()) + 3600)

    status = codex_oauth.authorization_status()

    assert status["authorized"] is True
    assert status["email"] == "user@example.com"
    assert status["accountIdSuffix"] == "123456"
    assert "access_token" not in status
    assert "refresh_token" not in status


def test_codex_multi_account_switches_active_credentials(monkeypatch, tmp_path):
    first_access = _write_auth(
        monkeypatch,
        tmp_path,
        expires_at=int(time.time()) + 3600,
        email="first@example.com",
        account_id="account-first",
    )
    second_access = _write_auth(
        monkeypatch,
        tmp_path,
        expires_at=int(time.time()) + 3600,
        email="second@example.com",
        account_id="account-second",
    )

    assert resolve_provider_request_credentials({"authMode": "codex"}).headers["Authorization"] == f"Bearer {second_access}"
    from src.provider_auth.store import list_accounts, set_active_account
    first_id = next(item["id"] for item in list_accounts("openai") if item["identity"] == "first@example.com")
    assert set_active_account("openai", first_id) is True
    assert resolve_provider_request_credentials({"authMode": "codex"}).headers["Authorization"] == f"Bearer {first_access}"


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


def test_codex_401_reloads_newer_credentials_before_forcing_refresh(monkeypatch):
    runtime = ResponsesRuntimeMethods()
    runtime.config = {"authMode": "codex"}
    calls = []

    def resolve(_config, *, force_refresh=False):
        calls.append(force_refresh)
        return ProviderRequestCredentials(
            base_url="https://chatgpt.com/backend-api/codex",
            headers={
                "Authorization": "Bearer reloaded",
                "ChatGPT-Account-ID": "account-1",
            },
        )

    monkeypatch.setattr(
        "src.provider_auth.resolve_provider_request_credentials",
        resolve,
    )
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer expired",
        "ChatGPT-Account-ID": "account-1",
    }

    assert runtime._reload_responses_auth_headers(headers) is True

    assert calls == [False]
    assert headers["Authorization"] == "Bearer reloaded"


def test_codex_401_forces_refresh_when_reloaded_credentials_are_unchanged(
    monkeypatch,
):
    runtime = ResponsesRuntimeMethods()
    runtime.config = {"authMode": "codex"}
    calls = []

    def resolve(_config, *, force_refresh=False):
        calls.append(force_refresh)
        token = "refreshed" if force_refresh else "expired"
        return ProviderRequestCredentials(
            base_url="https://chatgpt.com/backend-api/codex",
            headers={
                "Authorization": f"Bearer {token}",
                "ChatGPT-Account-ID": "account-1",
            },
        )

    monkeypatch.setattr(
        "src.provider_auth.resolve_provider_request_credentials",
        resolve,
    )
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer expired",
        "ChatGPT-Account-ID": "account-1",
    }

    assert runtime._reload_responses_auth_headers(headers) is False
    assert runtime._refresh_responses_auth_headers(headers) is True

    assert calls == [False, True]
    assert headers["Authorization"] == "Bearer refreshed"
