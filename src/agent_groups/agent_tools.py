"""Bind collaboration capabilities to a node identity and its current group.

No tool accepts an actor or graph identity from the model. Membership is checked
inside every domain transaction, including calls from an older in-flight run.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from .contracts import (BroadcastMessage, Contract, CreateTask, DirectMessage, Identifier,
                        MessageContent, PublishMessage, UpdateTask)
from .messages import GroupMessages
from .repository import GroupRepository
from .tasks import GroupTasks
from .settings import GroupSettings, read_group_settings
from .board_read import ReadBoard, ReadBoardDetail, board_detail, board_overview


class ReadEvents(Contract):
    after: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class EditTask(UpdateTask):
    task_id: Identifier


class GroupAgentTools:
    def __init__(self, repository: GroupRepository, group_id: str, node_id: str):
        self.repo = repository
        self.group_id = group_id
        self.node_id = node_id

    def board(self, **arguments):
        command = ReadBoard.model_validate(arguments)
        return board_overview(self.repo.get(self.group_id, self.node_id), command)

    def board_detail(self, **arguments):
        command = ReadBoardDetail.model_validate(arguments)
        return board_detail(self.repo.get(self.group_id, self.node_id), command)

    def events(self, **arguments):
        command = ReadEvents.model_validate(arguments)
        return self.repo.events(self.group_id, self.node_id, after=command.after, limit=command.limit)

    def message(self, **arguments):
        direct = DirectMessage.model_validate(arguments)
        command = PublishMessage(**direct.model_dump())
        return GroupMessages(self.repo).publish(self.group_id, command, self.node_id)

    def post_update(self, **arguments):
        update = MessageContent.model_validate(arguments)
        command = PublishMessage(**update.model_dump(), intent="update")
        return GroupMessages(self.repo).publish(self.group_id, command, self.node_id)

    def broadcast(self, **arguments):
        broadcast = BroadcastMessage.model_validate(arguments)
        command = PublishMessage(**broadcast.model_dump())
        return GroupMessages(self.repo).publish(self.group_id, command, self.node_id)

    def create_task(self, **arguments):
        command = CreateTask.model_validate(arguments)
        return GroupTasks(self.repo).create(self.group_id, command, self.node_id).model_dump()

    def update_task(self, **arguments):
        command = EditTask.model_validate(arguments)
        update = UpdateTask.model_validate(command.model_dump(exclude={"task_id"}, exclude_unset=True))
        return GroupTasks(self.repo).update(self.group_id, command.task_id, update, self.node_id).model_dump()

    def register(self, registry, settings: GroupSettings | None = None):
        settings = settings if settings is not None else read_group_settings()
        definitions = [
            ("group_board", ReadBoard, self.board),
            ("group_board_detail", ReadBoardDetail, self.board_detail),
            ("group_events", ReadEvents, self.events),
            ("group_send_message", DirectMessage, self.message),
            ("group_post_update", MessageContent, self.post_update),
            ("group_broadcast_message", BroadcastMessage, self.broadcast),
            ("group_create_task", CreateTask, self.create_task),
            ("group_update_task", EditTask, self.update_task),
        ]
        for name, contract, function in definitions:
            registry.register_external_tool({"type": "function", "function": {
                "name": name, "description": getattr(settings.tool_prompts, name), "parameters": contract.model_json_schema(),
            }}, function)


def bind_group_tools(agent, *, node_directory: str, node_id: str, role: str, access_role: str = "developer") -> bool:
    if not node_directory:
        return False
    graph_directory = Path(node_directory).parent
    if not (graph_directory / "groups.sqlite3").is_file():
        return False
    repository = GroupRepository(graph_directory, access_role=access_role)
    group = repository.member_group(node_id)
    if group is None:
        return False
    settings = read_group_settings()
    GroupAgentTools(repository, group.id, node_id).register(agent.tools, settings)
    context = {
        "your_node_id": node_id,
        "task_notifications": settings.task_notifications.model_dump(),
        "group": board_overview(group, ReadBoard()),
        "your_role": next(m.role for m in group.members if m.node_id == node_id),
    }
    agent.Message(role,
        settings.context_prompt + "\n"
        + json.dumps(context, ensure_ascii=False), persist=False)
    return True
