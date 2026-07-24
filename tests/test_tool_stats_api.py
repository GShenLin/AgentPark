from fastapi.testclient import TestClient


def test_tool_stats_api_forwards_graph_and_time_scope(monkeypatch):
    import src.web_backend as backend
    import src.web_backend.settings_api as settings_api

    calls = []

    def build_document(*, graph_id="", scope_hours=0):
        calls.append((graph_id, scope_hours))
        return {
            "summary": {"providers": {}},
            "recent_calls": [],
            "recent_calls_by_provider": {},
            "failure_analysis": {},
            "failure_analysis_by_provider": {},
            "turn_stats": {"providers": {}, "available_graph_ids": [], "scope": {}},
            "scope": {"graph_id": graph_id, "hours": scope_hours, "available_graph_ids": []},
        }

    monkeypatch.setattr(settings_api, "build_scoped_tool_stats_document", build_document)
    response = TestClient(backend.create_app()).get("/api/tool-stats?graph_id=test&scope_hours=168")

    assert response.status_code == 200
    assert calls == [("test", 168)]
    assert response.json()["scope"] == {"graph_id": "test", "hours": 168, "available_graph_ids": []}
