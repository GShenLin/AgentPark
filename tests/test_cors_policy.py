from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from src.web_backend.cors_policy import configured_cors_allow_origins
from src.web_backend.cors_policy import is_allowed_private_network_origin
from src.web_backend.facade import WebBackendFacade


def test_default_cors_policy_allows_localhost_regex(monkeypatch):
    monkeypatch.delenv("AGENTPARK_CORS_ALLOW_ORIGINS", raising=False)

    facade = WebBackendFacade()
    cors_layers = [m for m in facade.app.user_middleware if m.cls is CORSMiddleware]

    assert len(cors_layers) == 1
    assert cors_layers[0].kwargs["allow_origins"] == []
    assert "localhost" in cors_layers[0].kwargs["allow_origin_regex"]


def test_configured_cors_allow_origins_uses_explicit_env(monkeypatch):
    monkeypatch.setenv("AGENTPARK_CORS_ALLOW_ORIGINS", "https://example.test, http://tool.local:5173")

    assert configured_cors_allow_origins() == ["https://example.test", "http://tool.local:5173"]


def test_private_network_origin_policy_defaults_to_localhost(monkeypatch):
    monkeypatch.delenv("AGENTPARK_CORS_ALLOW_ORIGINS", raising=False)

    assert is_allowed_private_network_origin("http://localhost:5173") is True
    assert is_allowed_private_network_origin("http://127.0.0.1:3000") is True
    assert is_allowed_private_network_origin("https://example.test") is False


def test_private_network_access_header_requires_opt_in(monkeypatch):
    monkeypatch.delenv("AGENTPARK_ALLOW_PRIVATE_NETWORK_ACCESS", raising=False)
    facade = WebBackendFacade()

    @facade.app.get("/probe")
    def probe():
        return {"ok": True}

    client = TestClient(facade.app)
    response = client.options(
        "/probe",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Private-Network": "true",
        },
    )

    assert "access-control-allow-private-network" not in response.headers


def test_private_network_access_header_requires_allowed_origin(monkeypatch):
    monkeypatch.setenv("AGENTPARK_ALLOW_PRIVATE_NETWORK_ACCESS", "1")
    monkeypatch.delenv("AGENTPARK_CORS_ALLOW_ORIGINS", raising=False)
    facade = WebBackendFacade()

    @facade.app.get("/probe")
    def probe():
        return {"ok": True}

    client = TestClient(facade.app)
    response = client.options(
        "/probe",
        headers={
            "Origin": "https://example.test",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Private-Network": "true",
        },
    )

    assert "access-control-allow-private-network" not in response.headers


def test_private_network_access_header_allows_opted_in_localhost(monkeypatch):
    monkeypatch.setenv("AGENTPARK_ALLOW_PRIVATE_NETWORK_ACCESS", "1")
    monkeypatch.delenv("AGENTPARK_CORS_ALLOW_ORIGINS", raising=False)
    facade = WebBackendFacade()

    @facade.app.get("/probe")
    def probe():
        return {"ok": True}

    client = TestClient(facade.app)
    response = client.options(
        "/probe",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Private-Network": "true",
        },
    )

    assert response.headers["access-control-allow-private-network"] == "true"
