"""Host-owned workspace inspection; never infer a remote OS from its path."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Literal
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from src.providers.agent_environment_context import build_agent_environment_context
from src.providers.agent_project_instructions import build_agent_project_instructions_context
from src.runtime_environment import get_runtime_environment


class ProjectInstructions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    directory: str
    paths: list[str]
    text: str


class WorkspaceInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    working_path: str = Field(min_length=1)
    platform: Literal["windows", "linux", "macos", "termux", "android", "posix"]
    shell: str = Field(min_length=1)
    timezone: str = Field(min_length=1)
    utc_offset_seconds: int = Field(gt=-86400, lt=86400)
    project_instructions: ProjectInstructions


def inspect_workspace(working_path: str) -> WorkspaceInspection:
    from .operations import validate_working_path

    path = validate_working_path(working_path)
    agent = SimpleNamespace(config={"working_path": path})
    environment = get_runtime_environment()
    context = build_agent_environment_context(agent)
    instructions = build_agent_project_instructions_context(agent)
    offset = datetime.now().astimezone().utcoffset()
    if offset is None:
        raise RuntimeError("Execution host did not report a UTC offset.")
    return WorkspaceInspection(
        working_path=path, platform=environment.platform, shell=environment.shell,
        timezone=context["timezone"], utc_offset_seconds=int(offset.total_seconds()),
        project_instructions=ProjectInstructions(**(instructions or {
            "directory": path, "paths": [], "text": "",
        })),
    )
