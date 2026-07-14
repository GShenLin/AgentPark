from __future__ import annotations

from dataclasses import dataclass, field

from src.cli_commands.companion_live_events import CompanionLiveEventReducer
from src.cli_commands.companion_tool_render import render_tool_event_lines


@dataclass
class TranscriptItem:
    role: str
    text: str = ""
    status: str = ""


@dataclass
class TuiState:
    transcript: list[TranscriptItem] = field(default_factory=list)
    draft: str = ""
    cursor: int = 0
    prompt_history: list[str] = field(default_factory=list)
    history_index: int | None = None
    queued: list[str] = field(default_factory=list)
    running: bool = False
    status: str = "ready"
    should_exit: bool = False
    last_ctrl_c_at: float = 0.0
    active_assistant_index: int | None = None
    active_thinking_index: int | None = None
    key_events_seen: int = 0
    last_key: str = ""
    restart_requested: bool = False


class CompanionTuiLiveTranscript:
    def __init__(self, state: TuiState) -> None:
        self.state = state
        self.events = CompanionLiveEventReducer()
        self.turn_start_index = len(state.transcript)

    def begin_turn(self) -> None:
        self.events = CompanionLiveEventReducer()
        self.turn_start_index = len(self.state.transcript)
        self.state.transcript.append(TranscriptItem(role="assistant", text="", status="working"))
        self.state.active_assistant_index = len(self.state.transcript) - 1
        self.state.active_thinking_index = None

    def handle(self, payload: object) -> None:
        for action in self.events.consume(payload):
            if action.kind == "delta" and action.channel == "thinking":
                self._close_active_assistant()
                self._append_thinking(action.text)
            elif action.kind == "delta":
                self._close_active_thinking()
                self._append_assistant(action.text)
            elif action.kind == "close":
                self._close_active_fragments()
            elif action.kind == "activity":
                self._close_active_fragments()
                self.state.transcript.append(TranscriptItem(role="activity", text=action.text))
            elif action.kind == "tool" and action.event is not None:
                self._close_active_fragments()
                self.state.transcript.append(
                    TranscriptItem(role="tool", text="\n".join(render_tool_event_lines(action.event)))
                )
            elif action.kind == "server_tool" and action.event is not None:
                self._close_active_fragments()
                tool_type = str(action.event.get("tool_type") or "server_tool").strip() or "server_tool"
                status = str(action.event.get("status") or "in_progress").strip() or "in_progress"
                self.state.transcript.append(TranscriptItem(role="tool", text=f"server tool {tool_type}: {status}"))

    def finish(self, response: str, *, is_error: bool) -> None:
        if response and not self._latest_assistant_text():
            self._set_assistant(response)
        if not response and not self._latest_assistant_text():
            self._remove_empty_active_assistant()
        self._close_active_thinking()
        self._set_assistant_status("error" if is_error else "done")
        self.state.active_assistant_index = None

    def _append_assistant(self, text: str) -> None:
        if not text:
            return
        index = self._ensure_active_assistant()
        self.state.transcript[index].text += text

    def _set_assistant(self, text: str) -> None:
        if not text:
            return
        index = self._ensure_active_assistant()
        self.state.transcript[index].text = text

    def _active_assistant_text(self) -> str:
        index = self.state.active_assistant_index
        if index is None or index < 0 or index >= len(self.state.transcript):
            return ""
        return self.state.transcript[index].text

    def _latest_assistant_text(self) -> str:
        active = self._active_assistant_text()
        if active:
            return active
        for item in reversed(self.state.transcript[self.turn_start_index :]):
            if item.role == "assistant" and item.text:
                return item.text
        return ""

    def _set_assistant_status(self, status: str) -> None:
        index = self.state.active_assistant_index
        if index is not None and 0 <= index < len(self.state.transcript):
            self.state.transcript[index].status = status

    def _ensure_active_assistant(self) -> int:
        index = self.state.active_assistant_index
        if (
            index is not None
            and 0 <= index < len(self.state.transcript)
            and self.state.transcript[index].role == "assistant"
        ):
            return index
        self.state.transcript.append(TranscriptItem(role="assistant", text="", status="working"))
        self.state.active_assistant_index = len(self.state.transcript) - 1
        return self.state.active_assistant_index

    def _close_active_assistant(self) -> None:
        index = self.state.active_assistant_index
        if index is None or index < 0 or index >= len(self.state.transcript):
            self.state.active_assistant_index = None
            return
        item = self.state.transcript[index]
        if item.role != "assistant":
            self.state.active_assistant_index = None
            return
        if not item.text.strip():
            self._remove_empty_active_assistant()
            return
        item.status = "done"
        self.state.active_assistant_index = None

    def _append_thinking(self, text: str) -> None:
        if not text:
            return
        index = self.state.active_thinking_index
        if (
            index is None
            or index < 0
            or index >= len(self.state.transcript)
            or self.state.transcript[index].role != "thinking"
        ):
            self.state.transcript.append(TranscriptItem(role="thinking", text="", status="working"))
            index = len(self.state.transcript) - 1
            self.state.active_thinking_index = index
        self.state.transcript[index].text += text

    def _close_active_thinking(self) -> None:
        index = self.state.active_thinking_index
        if index is None or index < 0 or index >= len(self.state.transcript):
            self.state.active_thinking_index = None
            return
        item = self.state.transcript[index]
        if item.role == "thinking":
            item.status = "done"
        self.state.active_thinking_index = None

    def _close_active_fragments(self) -> None:
        self._close_active_thinking()
        self._close_active_assistant()

    def _remove_empty_active_assistant(self) -> None:
        index = self.state.active_assistant_index
        if index is None or index < 0 or index >= len(self.state.transcript):
            self.state.active_assistant_index = None
            return
        item = self.state.transcript[index]
        if item.role == "assistant" and not item.text.strip() and index == len(self.state.transcript) - 1:
            self.state.transcript.pop()
        self.state.active_assistant_index = None


__all__ = ["CompanionTuiLiveTranscript", "TranscriptItem", "TuiState"]
