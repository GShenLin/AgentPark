"""Restore a deleted member without overwriting work done by peers meanwhile."""
from contextlib import contextmanager
from pathlib import Path

from .contracts import Contract, GroupConflict, GroupMember, GroupTask, Identifier
from .repository import GroupRepository, timestamp


class DeletedMember(Contract):
    group_id: Identifier
    member: GroupMember
    tasks: list[GroupTask]


@contextmanager
def restore_deleted_member(graph_directory: str, snapshot: dict | None):
    if snapshot is None:
        yield
        return
    saved = DeletedMember.model_validate(snapshot)
    directory = Path(graph_directory)
    if not (directory / "groups.sqlite3").is_file():
        raise GroupConflict("original group store no longer exists")
    repo = GroupRepository(directory)
    with repo.transaction() as db:
        group = repo.read(db, saved.group_id)
        if db.execute("SELECT 1 FROM members WHERE node_id=?", (saved.member.node_id,)).fetchone():
            raise GroupConflict("restored node identity already belongs to a group")
        tasks = {task.id: task for task in group.tasks}
        for original in saved.tasks:
            current = tasks.get(original.id)
            if (current is None or current.revision != original.revision + 1
                    or current.owner_id is not None or current.status != "blocked"):
                raise GroupConflict("released task changed after deletion; undo would overwrite newer work")
        group.members.append(saved.member)
        for original in saved.tasks:
            restored = original.model_copy(update={"revision": tasks[original.id].revision + 1,
                                                   "updated_at": timestamp()})
            group.tasks[group.tasks.index(tasks[original.id])] = restored
        db.execute("INSERT INTO members VALUES(?,?)", (saved.member.node_id, group.id))
        repo.save(db, group)
        repo.event(db, group, "member_restored", None,
                   {"member": saved.member.model_dump(), "restored_task_ids": [t.id for t in saved.tasks]}, recipients=[])
        yield
