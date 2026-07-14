import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.web_backend.network_diagnostics import NetworkDiagnosticsMiddleware


def test_network_diagnostics_records_api_requests(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.web_backend.network_diagnostics._get_runtime_root",
        lambda: str(tmp_path),
    )
    app = FastAPI()
    app.add_middleware(NetworkDiagnosticsMiddleware)

    @app.get("/api/nodes")
    def list_nodes():
        return {"nodes": []}

    client = TestClient(app)
    response = client.get(
        "/api/nodes?source=mobile",
        headers={
            "Origin": "http://10.231.113.79:8788",
            "Referer": "http://10.231.113.79:8788/mobile",
            "User-Agent": "AgentPark mobile test",
        },
    )

    assert response.status_code == 200
    records = (tmp_path / "logs" / "network-requests.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(records) == 1
    record = json.loads(records[0])
    assert record["method"] == "GET"
    assert record["path"] == "/api/nodes"
    assert record["query"] == "source=mobile"
    assert record["status"] == 200
    assert record["origin"] == "http://10.231.113.79:8788"
    assert record["referer"] == "http://10.231.113.79:8788/mobile"
    assert record["user_agent"] == "AgentPark mobile test"
    assert record["duration_ms"] >= 0


def test_network_diagnostics_ignores_static_requests(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.web_backend.network_diagnostics._get_runtime_root",
        lambda: str(tmp_path),
    )
    app = FastAPI()
    app.add_middleware(NetworkDiagnosticsMiddleware)

    @app.get("/health")
    def health():
        return {"ok": True}

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert not (tmp_path / "logs" / "network-requests.jsonl").exists()
