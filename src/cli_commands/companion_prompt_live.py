from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from src.cli_commands.companion_live_events import CompanionLiveEventReducer
from src.cli_commands.companion_tool_render import render_tool_event_lines


@dataclass
class PromptLiveSection:
    role: str
    text: str


class PromptLiveTranscript:
    """Thread-safe live area rendered above the active PromptSession input."""

    def __init__(self, invalidate: Callable[[], None]) -> None:
        self.invalidate = invalidate
        self.events = CompanionLiveEventReducer()
        self._lock = threading.Lock()
        self._sections: list[PromptLiveSection] = []
        self._active_channel = ""

    def handle(self, payload: object) -> None:
        actions = self.events.consume(payload)
        if not actions:
            return
        with self._lock:
            for action in actions:
                if action.kind == "delta":
                    self._append_delta(action.channel, action.text)
                elif action.kind == "close":
                    self._active_channel = ""
                elif action.kind == "activity":
                    self._append_section("activity", action.text)
                elif action.kind == "tool" and action.event is not None:
                    self._append_section("tool", "\n".join(render_tool_event_lines(action.event)))
                elif action.kind == "server_tool" and action.event is not None:
                    tool_type = str(action.event.get("tool_type") or "server_tool").strip() or "server_tool"
                    status = str(action.event.get("status") or "in_progress").strip() or "in_progress"
                    self._append_section("tool", f"server tool {tool_type}: {status}")
        self.invalidate()

    def prompt_message(self):
        with self._lock:
            text = self._render_locked()
        if not text:
            return [("class:prompt", "> ")]
        return [("class:live", text + "\n"), ("class:prompt", "> ")]

    def commit(self) -> str:
        with self._lock:
            text = self._render_locked()
            self.events = CompanionLiveEventReducer()
            self._sections = []
            self._active_channel = ""
        self.invalidate()
        return text

    def _append_delta(self, channel: str, text: str) -> None:
        if not text:
            return
        if self._active_channel == channel and self._sections and self._sections[-1].role == channel:
            self._sections[-1].text += text
            return
        self._sections.append(PromptLiveSection(role=channel, text=text))
        self._active_channel = channel

    def _append_section(self, role: str, text: str) -> None:
        if not text:
            return
        self._sections.append(PromptLiveSection(role=role, text=text))
        self._active_channel = ""

    def _render_locked(self) -> str:
        blocks: list[str] = []
        for section in self._sections:
            body = section.text.replace("\r\n", "\n").replace("\r", "\n")
            indented = "\n".join(f"  {line}" for line in body.split("\n"))
            blocks.append(f"{section.role}\n{indented}")
        return "\n\n".join(blocks)


__all__ = ["PromptLiveSection", "PromptLiveTranscript"]
