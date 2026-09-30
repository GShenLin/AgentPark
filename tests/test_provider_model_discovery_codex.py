from types import SimpleNamespace

from src.provider_model_discovery import _models_endpoint, discover_provider_models


_CODEX_PROVIDER = {
    "type": "openai",
    "authMode": "codex",
    "baseUrl": "https://chatgpt.com/backend-api/codex",
}


def test_discovery_uses_installed_codex_version(monkeypatch):
    monkeypatch.delenv("CODEX_CLIENT_VERSION", raising=False)
    monkeypatch.setattr(
        "src.provider_model_discovery.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout="codex-cli 0.155.1\n"),
    )
    monkeypatch.setattr(
        "src.provider_model_discovery.resolve_provider_request_credentials",
        lambda provider: SimpleNamespace(headers={"Authorization": "Bearer test"}),
    )

    def fake_get(self, *, url, headers, timeout_sec, marker):
        assert url == "https://chatgpt.com/backend-api/codex/models?client_version=0.155.1"
        assert headers["Authorization"] == "Bearer test"
        return SimpleNamespace(status_code=200, body='{"models":[{"slug":"gpt-6-astra"},{"slug":"gpt-6-sol"}]}')

    monkeypatch.setattr("src.providers.curl_transport.CurlHttpTransport._curl_get_text_once_raw", fake_get)
    result = discover_provider_models(_CODEX_PROVIDER, timeout_seconds=1)
    assert result["supported"] is True
    assert result["model_ids"] == ["gpt-6-astra", "gpt-6-sol"]


def test_discovery_reports_missing_codex_version(monkeypatch):
    monkeypatch.delenv("CODEX_CLIENT_VERSION", raising=False)
    monkeypatch.setattr(
        "src.provider_model_discovery.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("codex")),
    )
    result = discover_provider_models(_CODEX_PROVIDER, timeout_seconds=1)
    assert result["supported"] is False
    assert "codexClientVersion" in result["reason"]
    assert result["endpoint"] == ""


def test_discovery_uses_configured_version_without_cli(monkeypatch):
    monkeypatch.delenv("CODEX_CLIENT_VERSION", raising=False)

    def unexpected_cli(*args, **kwargs):
        raise AssertionError("Configured version must not require a CLI on the server")

    monkeypatch.setattr("src.provider_model_discovery.subprocess.run", unexpected_cli)
    assert _models_endpoint(
        {**_CODEX_PROVIDER, "codexClientVersion": "0.155.1"},
        "openai",
    ) == "https://chatgpt.com/backend-api/codex/models?client_version=0.155.1"
