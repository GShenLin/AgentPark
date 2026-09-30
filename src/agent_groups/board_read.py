"""Explicit, paged agent views; the UI keeps the complete board document.

Long prose belongs in a revision-bound detail read, never silently truncated in
an overview. All reads still authorize the bound node against live membership.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .contracts import AgentGroup, Contract, GroupConflict, GroupNotFound, Identifier


class ReadBoard(Contract):
    task_offset: int = Field(default=0, ge=0)
    member_offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=10)
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_page_revision(self):
        if (self.task_offset or self.member_offset) and self.expected_revision is None:
            raise ValueError("continuation pages require expected_revision from group_board")
        return self


class ReadBoardDetail(Contract):
    section: Literal["objective", "member_role", "task_description", "task_evidence", "task_dependencies"]
    item_id: Identifier | None = None
    expected_revision: int = Field(ge=1)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=4000, ge=1, le=8000)

    @model_validator(mode="after")
    def require_item(self):
        if self.section == "objective" and self.item_id is not None:
            raise ValueError("objective has no item_id")
        if self.section != "objective" and self.item_id is None:
            raise ValueError("this section requires item_id")
        return self


def page(values, offset: int, limit: int):
    if offset > len(values):
        raise ValueError("offset is past the end")
    end = min(offset + limit, len(values))
    return {"items": values[offset:end], "total": len(values),
            "next_offset": end if end < len(values) else None}


def check_revision(group: AgentGroup, revision: int | None):
    if revision is not None and revision != group.revision:
        raise GroupConflict("board changed; read group_board again before continuing")


def board_overview(group: AgentGroup, command: ReadBoard):
    check_revision(group, command.expected_revision)
    members = [{"node_id": m.node_id, "role_chars": len(m.role)} for m in group.members]
    states = {task.id: task.status for task in group.tasks}
    tasks = [{"id": t.id, "title": t.title, "status": t.status, "owner_id": t.owner_id,
              "revision": t.revision, "description_chars": len(t.description),
              "evidence_chars": len(t.evidence), "dependency_count": len(t.dependencies),
              "unfinished_dependency_count": sum(states[dep] != "done" for dep in t.dependencies)}
             for t in group.tasks]
    return {"id": group.id, "name": group.name, "revision": group.revision,
            "objective_chars": len(group.objective),
            "members": page(members, command.member_offset, command.limit),
            "tasks": page(tasks, command.task_offset, command.limit),
            "detail_tool": "group_board_detail"}


def board_detail(group: AgentGroup, command: ReadBoardDetail):
    check_revision(group, command.expected_revision)
    if command.section == "objective":
        value = group.objective
    elif command.section == "member_role":
        member = next((m for m in group.members if m.node_id == command.item_id), None)
        if member is None:
            raise GroupNotFound("member not found")
        value = member.role
    else:
        task = next((t for t in group.tasks if t.id == command.item_id), None)
        if task is None:
            raise GroupNotFound("task not found")
        if command.section == "task_dependencies":
            return {"revision": group.revision, "section": command.section, "item_id": task.id,
                    **page(task.dependencies, command.offset, min(command.limit, 10))}
        value = task.description if command.section == "task_description" else task.evidence
    result = page(value, command.offset, command.limit)
    return {"revision": group.revision, "section": command.section, "item_id": command.item_id,
            "text": result["items"], "total_chars": result["total"], "next_offset": result["next_offset"]}
