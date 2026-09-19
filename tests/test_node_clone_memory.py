from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from src.long_term_memory.retrieval import MemoryReader
from src.long_term_memory.store import MemoryStore


@pytest.fixture
def clone_api(tmp_path, monkeypatch):
    import src.web_backend as backend
    from src.web_backend import runtime_paths
    from src.runtime_events import event_config_store

    root = tmp_path / "memories"
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(root))
    monkeypatch.setattr(event_config_store, "event_config_path", lambda: str(tmp_path / "events.json"))
    client = TestClient(backend.create_app())
    response = client.post("/api/nodes/instances", json={
        "node_id": "original", "type_id": "append_node", "graph_id": "source",
    })
    assert response.status_code == 200, response.text
    return client, root


@pytest.mark.parametrize("target_graph", ["source", "another_graph"])
def test_clone_preserves_memory_with_new_owner_and_independent_workers(clone_api, target_graph):
    client, root = clone_api
    source_dir = root / "source" / "original"
    source = MemoryStore(source_dir, "source", "original")
    note = source.add_note("Keep this preference")
    key = "a" * 64 + "-" + "b" * 32
    folder = source.root / "generations" / key
    folder.mkdir(parents=True)
    manifest = {"sources": {}, "notes": source.notes()}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "memory_summary.md").write_text("Remember the preference", encoding="utf-8")
    # Leave committed data in WAL while the connection remains open.
    with source.connect() as db:
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("UPDATE owner SET publication=?", (key,))
        db.execute("INSERT INTO jobs(name,token,lease_until,status) VALUES('pipeline','original-worker',?,'running')",
                   (time.time() + 600,))
        db.execute("INSERT INTO runs(started_at,status) VALUES(?,'running')", (time.time(),))
        db.execute("INSERT INTO suppressed VALUES('forgotten-source')")
        db.commit()
        assert source.path.with_name("state.sqlite3-wal").stat().st_size > 0
        before = source.state()
        response = client.post("/api/nodes/instances/original/clone?graph_id=source", json={
            "new_node_id": "copied", "target_graph_id": target_graph,
        })
        assert response.status_code == 200, response.text
        copied = MemoryStore(root / target_graph / "copied", target_graph, "copied")
        assert copied.notes() == source.notes()
        assert copied.notes()[0]["id"] == note
        assert MemoryReader(copied).summary() == "Remember the preference"
        with copied.connect() as clone_db:
            assert clone_db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 0
            assert clone_db.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
            assert clone_db.execute("SELECT id FROM suppressed").fetchone()[0] == "forgotten-source"
        copied.add_note("Only in the copy")
        assert len(source.notes()) == 1
        assert source.publication()["summary"] == "Remember the preference"
        assert source.state() == before
        assert db.execute("SELECT token FROM jobs").fetchone()[0] == "original-worker"


def test_clone_rejects_wrong_owner_and_removes_partial_node(clone_api):
    client, root = clone_api
    source = MemoryStore(root / "source" / "original", "source", "wrong-node")
    response = client.post("/api/nodes/instances/original/clone?graph_id=source", json={"new_node_id": "copied"})
    assert response.status_code == 500
    assert "owner or schema" in response.json()["detail"]
    assert not (root / "source" / "copied").exists()
    assert source.state()["node_id"] == "wrong-node"


def test_clone_without_memory_database_starts_with_new_owner(clone_api):
    client, root = clone_api
    response = client.post("/api/nodes/instances/original/clone?graph_id=source", json={"new_node_id": "copied"})
    assert response.status_code == 200, response.text
    copied = MemoryStore(root / "source" / "copied", "source", "copied")
    assert copied.notes() == []
    assert not (root / "source" / "original" / "long_term_memory").exists()


def test_clone_missing_publication_fails_without_damaging_source(clone_api):
    client, root = clone_api
    source = MemoryStore(root / "source" / "original", "source", "original")
    with source.connect() as db:
        db.execute("UPDATE owner SET publication='missing'")
    response = client.post("/api/nodes/instances/original/clone?graph_id=source", json={"new_node_id": "copied"})
    assert response.status_code == 500
    assert not (root / "source" / "copied").exists()
    assert source.state()["publication"] == "missing"
