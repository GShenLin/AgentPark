import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.agent_groups.contracts import CreateGroup, CreateTask, UpdateTask, PublishMessage, GroupPermissionError
from src.agent_groups.messages import GroupMessages
from src.agent_groups.membership import GroupMembership
from src.agent_groups.repository import GroupRepository
from src.agent_groups.tasks import GroupTasks


@pytest.fixture
def grouped_node(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir
    monkeypatch.setattr("src.web_backend.runtime_paths._get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr("src.web_backend.deletion_undo_store.deletion_undo_store.max_steps", lambda: 5)

    client = TestClient(backend.create_app())
    for graph in ("group-source", "group-target"):
        response = client.post(f"/api/graphs/{graph}", json={"graph": {"id": graph, "name": graph}})
        assert response.status_code == 200, response.text
    for node in ("Builder", "Peer"):
        response = client.post("/api/nodes/instances", json={
            "graph_id": "group-source", "node_id": node, "type_id": "agent_node"})
        assert response.status_code == 200, response.text
    root = Path(_get_graphs_dir())
    repo = GroupRepository(root / "group-source")
    group = GroupMembership(repo).create(CreateGroup.model_validate({
        "name": "Team", "members": [{"node_id": "Builder"}, {"node_id": "Peer"}],
        "bounds": {"x": 0., "y": 0., "width": 800., "height": 400.},
    }))
    tasks = GroupTasks(repo)
    task = tasks.create(group.id, CreateTask(title="Build", owner_id="Builder"), None)
    tasks.update(group.id, task.id, UpdateTask(expected_revision=1, status="in_progress"), "Builder")
    completed = tasks.create(group.id, CreateTask(title="Prototype", owner_id="Builder"), None)
    tasks.update(group.id, completed.id, UpdateTask(expected_revision=1, status="done", evidence="prototype.js tested"), "Builder")
    yield client, root, repo, group.id, task.id, completed.id
    client.close()


def snapshot(repo):
    with repo.connect() as db:
        return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                for table in ("groups", "members", "events", "deliveries", "message_requests")}


def move(client):
    return client.post("/api/nodes/instances/Builder/move?graph_id=group-source",
                       json={"target_graph_id": "group-target"})


def test_move_detaches_member_releases_work_and_cancels_notifications(grouped_node):
    client, root, repo, gid, task_id, completed_id = grouped_node
    response = move(client)
    assert response.status_code == 200, response.text
    assert (root / "group-target" / "Builder" / "config.json").is_file()
    assert not (root / "group-source" / "Builder").exists()
    assert repo.member_group("Builder") is None
    group = repo.get(gid)
    assert [member.node_id for member in group.members] == ["Peer"]
    task = next(t for t in group.tasks if t.id == task_id)
    assert (task.status, task.owner_id, task.revision) == ("blocked", None, 3)
    completed = next(t for t in group.tasks if t.id == completed_id)
    assert (completed.status, completed.owner_id, completed.evidence) == ("done", "Builder", "prototype.js tested")
    assert not any(d["node_id"] == "Builder" for d in repo.pending_deliveries())
    event = repo.events(gid)["events"][-1]
    assert event["kind"] == "member_left"
    assert event["payload"]["reason"] == "moved_to_graph:group-target"
    assert not (root / "group-target" / "groups.sqlite3").exists()


def test_failed_move_restores_directory_board_and_outbox(grouped_node, monkeypatch):
    from src.web_backend.node_instance_move import NodeInstanceMove
    client, root, repo, gid, *_ = grouped_node
    before = snapshot(repo)
    original = NodeInstanceMove._move_graph_references

    def fail_after_references(self, *args):
        original(self, *args)
        raise RuntimeError("injected failure after filesystem move")

    monkeypatch.setattr(NodeInstanceMove, "_move_graph_references", fail_after_references)
    response = move(client)
    assert response.status_code == 500
    assert "injected failure" in response.json()["detail"]
    assert snapshot(repo) == before
    assert repo.member_group("Builder").id == gid
    assert not (root / "group-target" / "Builder").exists()
    path = root / "group-source" / "Builder" / "config.json"
    assert json.loads(path.read_text(encoding="utf-8"))["graph_id"] == "group-source"


def test_busy_move_does_not_mutate_group(grouped_node):
    client, _, repo, *_ = grouped_node
    before = snapshot(repo)
    assert client.post("/api/nodes/instances/Builder/state?graph_id=group-source",
                       json={"state": "working"}).status_code == 200
    assert move(client).status_code == 409
    assert snapshot(repo) == before


def test_group_commit_failure_rolls_back_successful_filesystem_move(grouped_node, monkeypatch):
    client, root, repo, _, *_ = grouped_node
    before = snapshot(repo)
    original = GroupRepository.transaction

    @contextmanager
    def fail_commit(self):
        with original(self) as db:
            yield db
            raise RuntimeError("injected group commit failure")

    monkeypatch.setattr(GroupRepository, "transaction", fail_commit)
    response = move(client)
    assert response.status_code == 500
    assert "injected group commit failure" in response.json()["detail"]
    assert snapshot(repo) == before
    assert (root / "group-source" / "Builder" / "config.json").is_file()
    assert not (root / "group-target" / "Builder").exists()


def test_undo_commit_failure_retains_snapshot_and_leaves_group_deleted(grouped_node, monkeypatch):
    client, root, repo, *_ = grouped_node
    token = delete(client).json()["undo_token"]
    before = snapshot(repo)
    original = GroupRepository.transaction

    @contextmanager
    def fail_commit(self):
        with original(self) as db:
            yield db
            raise RuntimeError("injected undo commit failure")

    monkeypatch.setattr(GroupRepository, "transaction", fail_commit)
    response = client.post(f"/api/undo/{token}")
    assert response.status_code == 500
    assert snapshot(repo) == before
    assert not (root / "group-source" / "Builder").exists()
    from src.web_backend.deletion_undo_store import deletion_undo_store
    _, directory = deletion_undo_store.load(token)
    assert (Path(directory) / "node").is_dir()


def rename(client):
    return client.post("/api/nodes/instances/Builder/rename?graph_id=group-source",
                       json={"new_node_id": "Renamed"})


def test_rename_rebinds_task_ownership_direct_messages_and_request_identity(grouped_node):
    client, root, repo, gid, task_id, completed_id = grouped_node
    messages = GroupMessages(repo)
    sent = messages.publish(gid, PublishMessage(text="private plan", recipient_id="Builder", request_id="dm"), "Peer")
    reply = messages.publish(gid, PublishMessage(text="received plan", recipient_id="Peer", request_id="reply"), "Builder")
    response = rename(client)
    assert response.status_code == 200, response.text
    assert (root / "group-source" / "Renamed" / "config.json").is_file()
    assert not (root / "group-source" / "Builder").exists()
    group = repo.member_group("Renamed")
    assert group.id == gid
    assert repo.member_group("Builder") is None
    assert all(t.owner_id == "Renamed" for t in group.tasks)
    events = repo.events(gid, "Renamed")["events"]
    assert next(e for e in events if e["seq"] == sent["seq"])["payload"]["recipient_id"] == "Renamed"
    assert next(e for e in events if e["seq"] == reply["seq"])["actor_id"] == "Renamed"
    assert messages.publish(gid, PublishMessage(text="received plan", recipient_id="Peer", request_id="reply"),
                            "Renamed")["seq"] == reply["seq"]
    with pytest.raises(GroupPermissionError):
        repo.events(gid, "Builder")
    assert not any(d["node_id"] == "Builder" for d in repo.pending_deliveries())


def test_rename_failure_restores_artifacts_and_all_group_records(grouped_node, monkeypatch):
    import src.web_backend.node_instance_rename as module
    client, root, repo, *_ = grouped_node
    path = root / "group-source" / "Builder"
    (path / "Builder_note.md").write_text("keep this artifact", encoding="utf-8")
    before = snapshot(repo)

    def fail(*args):
        raise RuntimeError("injected graph rename failure")

    monkeypatch.setattr(module, "rename_node_references_in_graph", fail)
    response = rename(client)
    assert response.status_code == 500
    assert snapshot(repo) == before
    assert (path / "Builder_note.md").read_text(encoding="utf-8") == "keep this artifact"
    assert not (path / "Renamed_note.md").exists()
    assert not path.with_name("Renamed").exists()
    assert json.loads((path / "config.json").read_text(encoding="utf-8"))["node_id"] == "Builder"


def test_rename_commit_failure_restores_old_identity(grouped_node, monkeypatch):
    client, root, repo, *_ = grouped_node
    before = snapshot(repo)
    original = GroupRepository.transaction

    @contextmanager
    def fail_commit(self):
        with original(self) as db:
            yield db
            raise RuntimeError("injected rename commit failure")

    monkeypatch.setattr(GroupRepository, "transaction", fail_commit)
    response = rename(client)
    assert response.status_code == 500
    assert snapshot(repo) == before
    assert (root / "group-source" / "Builder" / "config.json").is_file()
    assert not (root / "group-source" / "Renamed").exists()


def test_active_node_rename_is_rejected_without_touching_group(grouped_node):
    client, root, repo, *_ = grouped_node
    before = snapshot(repo)
    assert client.post("/api/nodes/instances/Builder/state?graph_id=group-source",
                       json={"state": "working"}).status_code == 200
    assert rename(client).status_code == 409
    assert snapshot(repo) == before
    assert (root / "group-source" / "Builder" / "config.json").is_file()


def delete(client):
    return client.delete("/api/nodes/instances/Builder?graph_id=group-source")


def test_delete_and_undo_restore_member_role_and_released_work(grouped_node):
    client, root, repo, gid, task_id, _ = grouped_node
    response = delete(client)
    assert response.status_code == 200, response.text
    token = response.json()["undo_token"]
    assert token
    assert repo.member_group("Builder") is None
    assert not (root / "group-source" / "Builder").exists()
    task = next(t for t in repo.get(gid).tasks if t.id == task_id)
    assert (task.status, task.owner_id) == ("blocked", None)
    restored = client.post(f"/api/undo/{token}")
    assert restored.status_code == 200, restored.text
    assert repo.member_group("Builder").id == gid
    task = next(t for t in repo.get(gid).tasks if t.id == task_id)
    assert (task.status, task.owner_id, task.revision) == ("in_progress", "Builder", 4)
    assert (root / "group-source" / "Builder").is_dir()
    assert client.post(f"/api/undo/{token}").status_code == 404


@pytest.mark.parametrize("retain", [False, True])
def test_delete_group_commit_failure_restores_node_even_without_undo(grouped_node, monkeypatch, retain):
    client, root, repo, *_ = grouped_node
    monkeypatch.setattr("src.web_backend.deletion_undo_store.deletion_undo_store.max_steps", lambda: 5 if retain else 0)
    before = snapshot(repo)
    original = GroupRepository.transaction

    @contextmanager
    def fail_commit(self):
        with original(self) as db:
            yield db
            raise RuntimeError("injected delete group commit failure")

    monkeypatch.setattr(GroupRepository, "transaction", fail_commit)
    response = delete(client)
    assert response.status_code == 500
    assert snapshot(repo) == before
    assert (root / "group-source" / "Builder" / "config.json").is_file()


def test_successful_delete_without_undo_discards_ephemeral_archive(grouped_node, monkeypatch, tmp_path):
    client, root, repo, *_ = grouped_node
    monkeypatch.setattr("src.web_backend.deletion_undo_store.deletion_undo_store.max_steps", lambda: 0)
    response = delete(client)
    assert response.status_code == 200, response.text
    assert response.json()["undo_token"] is None
    assert repo.member_group("Builder") is None
    assert not (root / "group-source" / "Builder").exists()
    assert list((tmp_path / ".cache" / "undo").iterdir()) == []


def test_undo_does_not_overwrite_work_reassigned_after_deletion(grouped_node):
    client, root, repo, gid, task_id, _ = grouped_node
    token = delete(client).json()["undo_token"]
    GroupTasks(repo).update(gid, task_id, UpdateTask(expected_revision=3, owner_id="Peer",
                                                   status="in_progress"), "Peer")
    before = snapshot(repo)
    response = client.post(f"/api/undo/{token}")
    assert response.status_code == 409
    assert "newer work" in response.json()["detail"]
    assert snapshot(repo) == before
    assert not (root / "group-source" / "Builder").exists()
    from src.web_backend.deletion_undo_store import deletion_undo_store
    _, directory = deletion_undo_store.load(token)
    assert (Path(directory) / "node").is_dir()
