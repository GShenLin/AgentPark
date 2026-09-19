import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.web_backend import node_open_diagnostics as diagnostics
from src.web_backend.route_registry import ApiRouteRegistry

TRACE_ID = "fa1e8f98-7dc2-4c89-9975-1d1ec2c25ada"


def test_traced_response_keeps_body_and_captures_worker_phases(monkeypatch):
    records = []
    monkeypatch.setattr(diagnostics, "write_measurement", records.append)
    app = FastAPI()
    app.add_middleware(diagnostics.NodeOpenDiagnosticsMiddleware)

    @app.get("/api/sample")
    def sample():
        diagnostics.checkpoint("handler_enter")
        diagnostics.checkpoint("payload_ready", live_chars=100)
        return {"value": "中文"}

    with TestClient(app) as client:
        plain = client.get("/api/sample")
        assert records == []
        traced = client.get("/api/sample", headers={"x-node-open-trace": TRACE_ID, "x-node-open-request": "request-1"})
    assert plain.content == traced.content
    record = records[0]
    assert record["trace_id"] == TRACE_ID
    assert record["request_id"] == "request-1"
    assert record["body_bytes"] == len(traced.content)
    assert [phase["stage"] for phase in record["phases"]] == ["handler_enter", "payload_ready", "response_ready"]
    assert record["total_ms"] >= record["headers_ms"] >= 0
    assert diagnostics._request_trace.get() is None


def test_browser_report_validates_target_and_uses_node_visibility_dependency(monkeypatch):
    records, visible = [], []
    monkeypatch.setattr(diagnostics, "write_measurement", records.append)
    monkeypatch.setattr(ApiRouteRegistry, "ROUTES", [route for route in ApiRouteRegistry.ROUTES if route[1].endswith("/open-diagnostics")])
    core = SimpleNamespace(node_ops=SimpleNamespace(require_node_visible=lambda node, graph, request: visible.append((node, graph))))
    app = FastAPI()
    ApiRouteRegistry.register(app, core)
    payload = {
        "trace_id": TRACE_ID, "graph_id": "XYJ", "node_id": "Package1",
        "started_at": "2026-09-07T00:00:00Z",
        "events": [{"stage": "scroll_layout", "at_ms": 150, "metrics": {"height_read_ms": 42.5}}],
    }
    with TestClient(app) as client:
        url = "/api/nodes/instances/Package1/open-diagnostics?graph_id=XYJ"
        assert client.post(url, json=payload).status_code == 200
        assert visible == [("Package1", "XYJ")]
        payload["events"][0]["metrics"]["content"] = "must not accept log text"
        assert client.post(url, json=payload).status_code == 422
        del payload["events"][0]["metrics"]["content"]
        payload["graph_id"] = "wrong"
        assert client.post(url, json=payload).status_code == 400
    assert len(records) == 1


def test_file_sink_is_utf8_and_diagnostic_disk_failure_does_not_break_response(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(diagnostics, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(diagnostics, "_logger", None)
    diagnostics.write_measurement({"node_id": "打包"})
    assert json.loads((tmp_path / "logs/node-open-performance.jsonl").read_text(encoding="utf-8"))["node_id"] == "打包"
    for handler in diagnostics._logger.handlers:
        handler.close()

    def failed_write(record):
        raise OSError("disk full")

    monkeypatch.setattr(diagnostics, "write_measurement", failed_write)
    app = FastAPI()
    app.add_middleware(diagnostics.NodeOpenDiagnosticsMiddleware)

    @app.get("/api/sample")
    def sample():
        return {"ok": True}

    with TestClient(app) as client:
        assert client.get("/api/sample", headers={"x-node-open-trace": TRACE_ID}).json() == {"ok": True}
    assert "disk full" in capsys.readouterr().err
