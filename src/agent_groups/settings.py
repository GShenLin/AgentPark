"""Strict, workspace-wide group policy and editable model instructions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from pydantic import Field, StringConstraints

from src import workspace_settings
from .contracts import Contract
from .prompt_defaults import CONTEXT_PROMPT, NOTIFICATION_PROMPT, TOOL_PROMPTS


Prompt = Annotated[str, StringConstraints(max_length=32000)]


class ToolPrompts(Contract):
    group_board: Prompt = TOOL_PROMPTS["group_board"]
    group_board_detail: Prompt = TOOL_PROMPTS["group_board_detail"]
    group_events: Prompt = TOOL_PROMPTS["group_events"]
    group_send_message: Prompt = TOOL_PROMPTS["group_send_message"]
    group_post_update: Prompt = TOOL_PROMPTS["group_post_update"]
    group_broadcast_message: Prompt = TOOL_PROMPTS["group_broadcast_message"]
    group_create_task: Prompt = TOOL_PROMPTS["group_create_task"]
    group_update_task: Prompt = TOOL_PROMPTS["group_update_task"]


class TaskNotifications(Contract):
    assignment: bool = True
    dependency_ready: bool = True


class GroupSettings(Contract):
    context_prompt: Prompt = CONTEXT_PROMPT
    notification_prompt: Prompt = NOTIFICATION_PROMPT
    tool_prompts: ToolPrompts = Field(default_factory=ToolPrompts)
    task_notifications: TaskNotifications = Field(default_factory=TaskNotifications)


def group_settings_path() -> Path:
    return Path(workspace_settings.get_workspace_root()) / "config" / "group.json"


def read_group_settings() -> GroupSettings:
    path = group_settings_path()
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return GroupSettings()
    # Invalid saved configuration is an error, never a silent return to defaults.
    return GroupSettings.model_validate(json.loads(content))
