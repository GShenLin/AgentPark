import json
import subprocess

import pytest

from src.provider_model_discovery import discover_provider_models
from src.providers.curl_types import CurlResponse, CurlTransportError


_CODEX_PROVIDER = {
    "type": "openai",
    "authMode": "codex",
    "baseUrl": "https://chatgpt.com/backend-api/codex",
}
_REGISTRY = "https://registry.npmjs.org/@openai/codex/latest"


def test_discovery_reads_online_latest_each_time_without_local_cli(monkeypatch):
    versions = iter(["0.162.0", "0.163.0"])
    requested = []
    monkeypatch.setenv("CODEX_CLIENT_VERSION", "0.155.1")

    def unexpected_cli(*args, **kwargs):
        raise AssertionError("Model discovery must not invoke the local CLI")

    monkeypatch.setattr(subprocess, "run", unexpected_cli)

    def registry_request(self, **kwargs):
        assert kwargs["url"] == _REGISTRY
        assert kwargs["timeout_sec"] == 2
        assert kwargs["headers"] == {"Accept": "application/json", "Cache-Control": "no-cache"}
        return CurlResponse(json.dumps({"name": "@openai/codex", "version": next(versions)}), 200)

    monkeypatch.setattr("src.providers.curl_transport.CurlHttpTransport.request", registry_request)
    monkeypatch.setattr(
        "src.provider_model_discovery.resolve_provider_request_credentials",
        lambda provider: type("Credentials", (), {"headers": {"Authorization": "Bearer test"}})(),
    )

    def model_request(self, *, url, headers, timeout_sec, marker):
        requested.append(url)
        assert headers["Authorization"] == "Bearer test"
        return CurlResponse('{"models":[{"slug":"gpt-6.1-sol"}]}', 200)

    monkeypatch.setattr("src.providers.curl_transport.CurlHttpTransport._curl_get_text_once_raw", model_request)
    for _ in range(2):
        result = discover_provider_models(
            {**_CODEX_PROVIDER, "codexClientVersion": "0.155.1"}, timeout_seconds=2,
        )
        assert result["supported"] is True
        assert result["model_ids"] == ["gpt-6.1-sol"]
    assert requested == [
        f"https://chatgpt.com/backend-api/codex/models?client_version={version}"
        for version in ("0.162.0", "0.163.0")
    ]


@pytest.mark.parametrize("response, reason", [
    (CurlResponse("unavailable", 503), "HTTP 503"),
    (CurlResponse("not json", 200), "Cannot fetch latest Codex version"),
    (CurlResponse("[]", 200), "package @openai/codex"),
    (CurlResponse('{"name":"other","version":"0.162.0"}', 200), "package @openai/codex"),
    (CurlResponse('{"name":"@openai/codex"}', 200), "stable Codex version"),
    (CurlResponse('{"name":"@openai/codex","version":162}', 200), "stable Codex version"),
    (CurlResponse('{"name":"@openai/codex","version":"0.162.0-alpha.1"}', 200), "stable Codex version"),
    (CurlResponse('{"name":"@openai/codex","version":"0.162.0&extra=1"}', 200), "stable Codex version"),
    (CurlTransportError("connection timed out"), "connection timed out"),
])
def test_registry_failure_is_reported_without_model_request(monkeypatch, response, reason):
    def registry_request(self, **kwargs):
        if isinstance(response, Exception):
            raise response
        return response

    def unexpected_credentials(provider):
        raise AssertionError("Do not authenticate or query models after registry failure")

    monkeypatch.setattr("src.providers.curl_transport.CurlHttpTransport.request", registry_request)
    monkeypatch.setattr("src.provider_model_discovery.resolve_provider_request_credentials", unexpected_credentials)
    result = discover_provider_models(_CODEX_PROVIDER, timeout_seconds=1)
    assert result["supported"] is False
    assert _REGISTRY in result["reason"]
    assert reason in result["reason"]
    assert result["model_ids"] == []
    assert result["endpoint"] == ""


def test_api_key_provider_does_not_query_codex_registry(monkeypatch):
    def unexpected_registry(self, **kwargs):
        raise AssertionError("API key model discovery must not query the Codex version")

    monkeypatch.setattr("src.providers.curl_transport.CurlHttpTransport.request", unexpected_registry)
    monkeypatch.setattr(
        "src.providers.curl_transport.CurlHttpTransport._curl_get_text_once_raw",
        lambda self, **kwargs: CurlResponse('{"data":[{"id":"example-model"}]}', 200),
    )
    result = discover_provider_models(
        {"type": "openai", "apiKey": "test", "baseUrl": "https://example.test/v1"},
        timeout_seconds=1,
    )
    assert result["supported"] is True
    assert result["endpoint"] == "https://example.test/v1/models"
