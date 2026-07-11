from fastapi.testclient import TestClient
from starlette.middleware.cors import CORSMiddleware

from src.web_backend.facade import WebBackendFacade
from src.web_backend.private_network_access import PrivateNetworkAccessMiddleware


def test_cors_policy_allows_all_origins():
    facade = WebBackendFacade()
    cors_layers = [m for m in facade.app.user_middleware if m.cls is CORSMiddleware]

    assert len(cors_layers) == 1
    assert cors_layers[0].kwargs["allow_origins"] == ["*"]
    assert cors_layers[0].kwargs["allow_methods"] == ["*"]
    assert cors_layers[0].kwargs["allow_headers"] == ["*"]
    assert "allow_private_network" not in cors_layers[0].kwargs

    private_network_layers = [
        m for m in facade.app.user_middleware if m.cls is PrivateNetworkAccessMiddleware
    ]
    assert len(private_network_layers) == 1


def test_private_network_access_header_allows_any_origin():
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

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-private-network"] == "true"
