from __future__ import annotations

import uuid

from .contracts import CreateTask, GroupConflict, GroupPermissionError, GroupTask, UpdateTask
from .repository import GroupRepository, timestamp
from .task_notifications import task_actions


def validate_task(group, task: GroupTask):
    members = {member.node_id for member in group.members}
    if task.owner_id is not None and task.owner_id not in members:
        raise GroupConflict("task owner must be a current group member")
    if len(set(task.dependencies)) != len(task.dependencies):
        raise GroupConflict("task dependencies must be unique")
    tasks = {item.id: item for item in group.tasks}
    tasks[task.id] = task
    if any(dep not in tasks for dep in task.dependencies):
        raise GroupConflict("dependency task not found")
    visiting, visited = set(), set()

    def walk(task_id):
        if task_id in visiting:
            raise GroupConflict("task dependencies cannot contain cycles")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dep in tasks[task_id].dependencies:
            walk(dep)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in tasks:
        walk(task_id)
    if task.status in ("in_progress", "done"):
        if task.owner_id is None:
            raise GroupConflict("active/completed tasks require an owner")
        if any(tasks[dep].status != "done" for dep in task.dependencies):
            raise GroupConflict("finish task dependencies first")
    if task.status == "done" and not task.evidence.strip():
        raise GroupConflict("completed tasks require an evidence note")


class GroupTasks:
    def __init__(self, repository: GroupRepository):
        self.repo = repository

    def create(self, group_id: str, command: CreateTask, actor_id: str | None) -> GroupTask:
        now = timestamp()
        task = GroupTask(id=uuid.uuid4().hex, **command.model_dump(), created_at=now, updated_at=now)
        with self.repo.transaction() as db:
            group = self.repo.read(db, group_id, actor_id)
            validate_task(group, task)
            group.tasks.append(task)
            self.repo.save(db, group)
            actions = task_actions(group, task, actor_id=actor_id)
            self.repo.event(db, group, "task_created", actor_id,
                            {"task": task.model_dump(), "action_tasks": actions},
                            recipients=list(actions), notify_actor=True)
            return task

    def update(self, group_id: str, task_id: str, command: UpdateTask, actor_id: str | None) -> GroupTask:
        with self.repo.transaction() as db:
            group = self.repo.read(db, group_id, actor_id)
            current = next((item for item in group.tasks if item.id == task_id), None)
            if current is None:
                raise GroupConflict("task not found")
            if current.revision != command.expected_revision:
                raise GroupConflict("task changed; refresh before updating")
            if actor_id is not None and current.owner_id not in (None, actor_id):
                raise GroupPermissionError("only the task owner or user can change an owned task")
            changes = command.model_dump(exclude_unset=True, exclude={"expected_revision"})
            # Claiming is an atomic update, never a read-then-write agreement between agents.
            if actor_id is not None and changes.get("owner_id") not in (None, actor_id, current.owner_id):
                raise GroupPermissionError("an agent can claim a task only for itself")
            candidate = GroupTask.model_validate({**current.model_dump(), **changes})
            if candidate == current:
                return current
            validate_task(group, candidate)
            if current.status == "done" and candidate.status != "done":
                dependents = [t for t in group.tasks if task_id in t.dependencies and t.status in ("in_progress", "done")]
                if dependents:
                    raise GroupConflict("reopen dependent tasks before reopening this task")
            candidate.revision += 1
            candidate.updated_at = timestamp()
            group.tasks = [candidate if item.id == task_id else item for item in group.tasks]
            self.repo.save(db, group)
            actions = task_actions(group, candidate, current, actor_id=actor_id)
            self.repo.event(db, group, "task_updated", actor_id,
                            {"task": candidate.model_dump(), "action_tasks": actions},
                            recipients=list(actions), notify_actor=True)
            return candidate
