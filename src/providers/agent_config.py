"""Provider-independent invocation contract; node metadata is not provider input."""
from __future__ import annotations

from dataclasses import dataclass, fields
from copy import deepcopy
from typing import Callable


@dataclass(frozen=True)
class AgentConfig:
    run_tools: bool = True
    mode: str = "chat"
    web_search: str | None = None
    thinking: str | None = None
    reasoning_effort: str | None = None
    reasoning_summary: str | None = None
    stream: bool = False
    mode_options: dict | None = None

    def __post_init__(self):
        for name in ("run_tools", "stream"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"AgentConfig.{name} must be a boolean")
        if not isinstance(self.mode, str) or not self.mode.strip():
            raise ValueError("AgentConfig.mode must be a non-empty string")
        for name in ("web_search", "thinking", "reasoning_effort", "reasoning_summary"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"AgentConfig.{name} must be a string or None")
        for name in ("web_search", "thinking"):
            if getattr(self, name) not in {None, "", "enabled", "disabled", "auto"}:
                raise ValueError(f"AgentConfig.{name} must be enabled, disabled, or auto")
        if self.reasoning_summary not in {None, "", "auto", "concise", "detailed", "disabled"}:
            raise ValueError("AgentConfig.reasoning_summary is invalid")
        if self.reasoning_effort not in {None, "", "none", "minimal", "low", "medium", "high",
                                          "xhigh", "max", "ultra", "auto"}:
            raise ValueError("AgentConfig.reasoning_effort is invalid")
        if self.mode_options is not None and not isinstance(self.mode_options, dict):
            raise TypeError("AgentConfig.mode_options must be a dict or None")

    def values(self) -> dict:
        return {field.name: deepcopy(getattr(self, field.name)) for field in fields(self)}


@dataclass(frozen=True)
class AgentSendContext:
    """Per-call inputs, separate from the configuration compiled at creation."""
    tools: list | None = None
    run_tools: bool | None = None
    stream_handler: Callable | None = None
    thinking_stream_handler: Callable | None = None

    def values(self) -> dict:
        if self.tools is not None and not isinstance(self.tools, list):
            raise TypeError("AgentSendContext.tools must be a list or None")
        if self.run_tools is not None and type(self.run_tools) is not bool:
            raise TypeError("AgentSendContext.run_tools must be a boolean or None")
        for name in ("stream_handler", "thinking_stream_handler"):
            value = getattr(self, name)
            if value is not None and not callable(value):
                raise TypeError(f"AgentSendContext.{name} must be callable or None")
        return {field.name: getattr(self, field.name) for field in fields(self)
                if getattr(self, field.name) is not None}
