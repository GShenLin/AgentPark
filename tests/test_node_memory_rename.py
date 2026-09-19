from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.long_term_memory.jobs import PipelineLease
from src.long_term_memory.store import MemoryStore


@pytest.fixture
def node():
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    client = TestClient(backend.create_app())
    response = client.post("/api/nodes/instances", json={
        "node_id": "source", "type_id": "agent_node", "graph_id": "memory-rename",
    })
    assert response.status_code == 200
    folder = Path(_get_graphs_dir()) / "memory-rename" / "source"
    return client, folder


def rename(client):
    return client.post("/api/nodes/instances/source/rename?graph_id=memory-rename",
                       json={"new_node_id": "target"})


def test_rename_rebinds_memory_and_preserves_notes_and_history(node):
    client, folder = node
    store = MemoryStore(folder, "memory-rename", "source")
    store.add_note("Keep this user preference")
    notes = store.notes()
    history = b'{"role":"user","content":"original history"}\n'
    (folder / "messages.jsonl").write_bytes(history)
    revision = store.state()["revision"]

    response = rename(client)
    assert response.status_code == 200, response.text
    target = folder.with_name("target")
    assert not folder.exists()
    renamed = MemoryStore(target, "memory-rename", "target")
    assert renamed.notes() == notes
    assert renamed.state()["revision"] == revision + 1
    assert (target / "messages.jsonl").read_bytes() == history
    with pytest.raises(ValueError, match="owner"):
        MemoryStore(target, "memory-rename", "source")


def test_rename_rejects_active_memory_pipeline_before_moving(node):
    client, folder = node
    store = MemoryStore(folder, "memory-rename", "source")
    lease = PipelineLease(store, 30)
    assert lease.claim()
    try:
        response = rename(client)
        assert response.status_code == 409
        assert folder.is_dir()
        assert not folder.with_name("target").exists()
        assert store.state()["node_id"] == "source"
    finally:
        lease.finish()


@pytest.mark.parametrize("graph,node_id", [("wrong-graph", "source"), ("memory-rename", "wrong-node")])
def test_rename_rolls_back_directory_when_memory_owner_is_unexpected(node, graph, node_id):
    client, folder = node
    store = MemoryStore(folder, graph, node_id)
    before = store.state()
    response = rename(client)
    assert response.status_code == 500
    assert "owner" in response.json()["detail"]
    assert folder.is_dir()
    assert not folder.with_name("target").exists()
    assert store.state() == before
