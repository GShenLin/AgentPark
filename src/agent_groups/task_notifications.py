"""Derive actionable recipients from task transitions, never from prose."""
from .contracts import AgentGroup, GroupTask


def ready(group: AgentGroup, task: GroupTask) -> bool:
    states = {item.id: item.status for item in group.tasks}
    return bool(task.owner_id and task.status != "done"
                and all(states[dependency] == "done" for dependency in task.dependencies))


def task_actions(group: AgentGroup, task: GroupTask, previous: GroupTask | None = None,
                 *, actor_id: str | None = None) -> dict[str, list[str]]:
    actions = {}
    # Assignment or changed requirements need the owner. Routine evidence/status
    # edits remain visible on the board without waking unrelated specialists.
    if task.owner_id != actor_id and ready(group, task) and (
        previous is None or previous.owner_id != task.owner_id
        or previous.title != task.title
        or previous.description != task.description
        or previous.dependencies != task.dependencies
        or (previous.status != task.status and task.status in ("todo", "in_progress"))
    ):
        actions.setdefault(task.owner_id, []).append(task.id)
    if task.status == "done" and previous is not None and previous.status != "done":
        for dependent in group.tasks:
            if task.id in dependent.dependencies and ready(group, dependent):
                actions.setdefault(dependent.owner_id, []).append(dependent.id)
    return actions
