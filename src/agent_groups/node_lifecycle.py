"""Group state participates in node operations, rather than repairing it later."""
from contextlib import contextmanager
import json
from pathlib import Path

from .contracts import AgentGroup, GroupConflict
from .repository import GroupRepository, timestamp


def detach_member(repo, db, group, node_id: str, *, reason: str = "left"):
    group.members = [member for member in group.members if member.node_id != node_id]
    released = []
    for task in group.tasks:
        if task.owner_id == node_id and task.status != "done":
            task.owner_id = None
            task.status = "blocked"
            task.revision += 1
            task.updated_at = timestamp()
            released.append(task.model_dump())
    db.execute("DELETE FROM members WHERE node_id=?", (node_id,))
    db.execute("""UPDATE deliveries SET state='cancelled' WHERE node_id=? AND state='pending'
        AND event_seq IN (SELECT seq FROM events WHERE group_id=?)""", (node_id, group.id))
    repo.save(db, group)
    repo.event(db, group, "member_left", None,
               {"node_id": node_id, "reason": reason, "released_tasks": released}, recipients=[])


@contextmanager
def node_departure(graph_directory: str, node_id: str, *, reason: str):
    """Commit membership/outbox only if the enclosing filesystem operation succeeds.

    Caller owns filesystem rollback, including a failure committing this context.
    Enter after cancelling active execution for deletion; moves require idle
    reservation. The database write lock prevents concurrent membership changes.
    Completed tasks retain historical author attribution.
    """
    directory = Path(graph_directory)
    if not (directory / "groups.sqlite3").is_file():
        yield
        return
    repo = GroupRepository(directory)
    with repo.transaction() as db:
        row = db.execute("SELECT group_id FROM members WHERE node_id=?", (node_id,)).fetchone()
        snapshot = None
        if row is not None:
            group = repo.read(db, row[0])
            snapshot = {"group_id": group.id,
                        "member": next(m.model_dump() for m in group.members if m.node_id == node_id),
                        "tasks": [t.model_dump() for t in group.tasks if t.owner_id == node_id and t.status != "done"]}
            detach_member(repo, db, group, node_id, reason=reason)
        yield snapshot


def _rename_references(value, old: str, new: str):
    """Only identity fields change. Authored prose and request IDs are immutable."""
    if isinstance(value, list):
        return [_rename_references(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: new if key in {"node_id", "owner_id", "actor_id", "recipient_id"} and item == old
                else _rename_references(item, old, new) for key, item in value.items()}
    return value


@contextmanager
def node_rename(graph_directory: str, old: str, new: str):
    directory = Path(graph_directory)
    if old == new or not (directory / "groups.sqlite3").is_file():
        yield
        return
    repo = GroupRepository(directory)
    with repo.transaction() as db:
        # Combining two historical identities could expose old direct messages.
        if (db.execute("SELECT 1 FROM members WHERE node_id=?", (new,)).fetchone()
                or db.execute("SELECT 1 FROM deliveries WHERE node_id=?", (new,)).fetchone()
                or db.execute("SELECT 1 FROM events WHERE actor_id=?", (new,)).fetchone()):
            raise GroupConflict("target name already identifies a member in group history")
        current = db.execute("SELECT group_id FROM members WHERE node_id=?", (old,)).fetchone()
        changed_current = None
        for row in db.execute("SELECT id,document FROM groups").fetchall():
            before = json.loads(row["document"])
            after = _rename_references(before, old, new)
            if before != after:
                for previous, task in zip(before["tasks"], after["tasks"]):
                    if previous["owner_id"] != task["owner_id"]:
                        task["revision"] += 1
                        task["updated_at"] = timestamp()
                group = AgentGroup.model_validate(after)
                repo.save(db, group)
                if current and group.id == current[0]:
                    changed_current = group
        db.execute("UPDATE members SET node_id=? WHERE node_id=?", (new, old))
        db.execute("UPDATE deliveries SET node_id=? WHERE node_id=?", (new, old))
        for row in db.execute("SELECT seq,actor_id,payload FROM events").fetchall():
            payload = json.loads(row["payload"])
            updated = _rename_references(payload, old, new)
            if payload != updated or row["actor_id"] == old:
                db.execute("UPDATE events SET actor_id=?,payload=? WHERE seq=?",
                           (new if row["actor_id"] == old else row["actor_id"],
                            json.dumps(updated, ensure_ascii=False), row["seq"]))
        for row in db.execute("SELECT rowid,* FROM message_requests").fetchall():
            command = json.loads(row["command"])
            updated = _rename_references(command, old, new)
            if command != updated or row["actor_key"] == "node:" + old:
                from .contracts import PublishMessage
                db.execute("UPDATE message_requests SET actor_key=?,command=? WHERE rowid=?",
                           ("node:" + new if row["actor_key"] == "node:" + old else row["actor_key"],
                            PublishMessage.model_validate(updated).model_dump_json(
                                exclude={"attachments"} if not updated.get("attachments") else set()), row["rowid"]))
        if changed_current:
            repo.event(db, changed_current, "member_renamed", None, {"old_node_id": old, "node_id": new}, recipients=[])
        yield
