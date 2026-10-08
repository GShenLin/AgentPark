from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.cron.node_lifecycle import cron_node_departure, cron_node_rename
from src.cron.repository import CronRepository
from src.cron.schedule import CreateJob
from src.web_backend.memory_static_files import VisibilityAwareMemoriesStaticFiles


def test_rename_and_departure_preserve_ownership_with_rollback(tmp_path):
    repo = CronRepository(tmp_path)
    repo.create("agent", CreateJob(name="check", prompt="Check status",
        schedule={"kind": "every", "seconds": 60}), "developer", 1000)
    repo.materialize_due(1060)
    with pytest.raises(RuntimeError):
        with cron_node_departure(str(tmp_path), "agent"):
            raise RuntimeError("filesystem operation failed")
    assert len(repo.pending_runs()) == 1
    with cron_node_rename(str(tmp_path), "agent", "renamed"):
        pass
    assert repo.list("agent")["jobs"] == []
    assert len(repo.list("renamed")["jobs"]) == 1
    assert repo.pending_runs()[0]["node_id"] == "renamed"
    with cron_node_departure(str(tmp_path), "renamed"):
        pass
    assert repo.pending_runs() == []
    assert repo.list("renamed")["jobs"] == []


def test_database_and_journals_are_never_served(tmp_path):
    graph = tmp_path / "graph"
    graph.mkdir()
    app = FastAPI()
    app.mount("/memories", VisibilityAwareMemoriesStaticFiles(directory=str(tmp_path), core=SimpleNamespace()))
    with TestClient(app) as client:
        for suffix in ("", "-wal", "-shm", "-journal"):
            (graph / ("cron.sqlite3" + suffix)).write_text("private schedule data", encoding="utf-8")
            assert client.get("/memories/graph/cron.sqlite3" + suffix).status_code == 404


@pytest.mark.parametrize("action", ["rename", "move", "delete"])
def test_node_api_updates_cron_ownership(tmp_path, monkeypatch, action):
    import src.web_backend as backend

    monkeypatch.setattr("src.web_backend.runtime_paths._get_runtime_root", lambda: str(tmp_path))
    # Do not start live services: these requests exercise the actual lifecycle handlers.
    client = TestClient(backend.create_app())
    try:
        for graph in ("source", "target"):
            response = client.post(f"/api/graphs/{graph}", json={"graph": {"id": graph, "name": graph}})
            assert response.status_code == 200, response.text
        response = client.post("/api/nodes/instances", json={"graph_id": "source", "node_id": "Agent", "type_id": "agent_node"})
        assert response.status_code == 200, response.text
        repo = CronRepository(tmp_path / "memories" / "source")
        repo.create("Agent", CreateJob(name="check", prompt="Check status",
            schedule={"kind": "every", "seconds": 60}), "developer", 1000)
        url = "/api/nodes/instances/Agent"
        if action == "rename":
            response = client.post(url + "/rename?graph_id=source", json={"new_node_id": "Renamed"})
        elif action == "move":
            response = client.post(url + "/move?graph_id=source", json={"target_graph_id": "target"})
        else:
            response = client.delete(url + "?graph_id=source")
        assert response.status_code == 200, response.text
        assert repo.list("Agent")["jobs"] == []
        assert len(repo.list("Renamed")["jobs"]) == (1 if action == "rename" else 0)
    finally:
        client.close()
