from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.companion_inbox import drain_companion_notices
from src.companion_inbox import format_companion_notice
from src.cli_commands.companion_console import ConsoleEvent, ConsoleEventReader, MsvcrtConsole, TerminalScreen, WindowsConsole
from src.cli_commands.companion_debug import build_terminal_debug_text
from src.cli_commands.companion_restart import launch_restart_bat
from src.cli_commands.companion_tui_render import render_tui_text


TurnRunner = Callable[..., dict[str, Any]]


HELP_LINES = [
    "/help      show commands",
    "/status    show config and runtime paths",
    "/restart  run Restart.bat and exit this CLI session",
    "/clear     clear transcript",
    "/exit      quit",
    "Enter      submit",
    "Ctrl+C     clear draft, then quit when draft is empty",
    "Ctrl+U     clear draft",
    "Up/Down    recall prompt history",
]


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
    key_events_seen: int = 0
    last_key: str = ""
    restart_requested: bool = False


class CompanionTui:
    def __init__(
        self,
        target: Any,
        *,
        debug_terminal: bool,
        run_turn: TurnRunner,
        backend: str = "msvcrt",
        log_path: str = "",
    ) -> None:
        self.target = target
        self.debug_terminal = debug_terminal
        self.run_turn = run_turn
        self.backend = backend
        self.log_path = log_path
        self.state = TuiState()
        self.worker_events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.spinner_index = 0
        self.started_at = time.monotonic()
        self.last_inbox_check = 0.0

    @classmethod
    def is_available(cls) -> bool:
        return MsvcrtConsole.is_available() or WindowsConsole.is_available()

    @classmethod
    def availability_report(cls) -> str:
        return f"msvcrt=({MsvcrtConsole.availability_report()}), win32=({WindowsConsole.availability_report()})"

    @classmethod
    def backend_available(cls, backend: str) -> bool:
        if backend == "msvcrt":
            return MsvcrtConsole.is_available()
        if backend == "win32":
            return WindowsConsole.is_available()
        return False

    @classmethod
    def backend_report(cls, backend: str) -> str:
        if backend == "msvcrt":
            return MsvcrtConsole.availability_report()
        if backend == "win32":
            return WindowsConsole.availability_report()
        return "unknown backend"

    def run(self) -> None:
        self._seed_intro()
        self._log("tui_start", f"backend={self.backend}")
        with self._open_backend() as console, TerminalScreen(title=self._terminal_title()) as screen:
            reader = ConsoleEventReader(console)
            reader.start()
            self._render(screen)
            while not self.state.should_exit:
                event = reader.get(timeout=0.08)
                if event is not None:
                    self._handle_console_event(event)
                self._drain_inbox()
                self._drain_worker_events()
                if self.state.running:
                    self.spinner_index = (self.spinner_index + 1) % 4
                self._render(screen)
        self._log("tui_stop", "exit")
        return "restart" if self.state.restart_requested else ""

    def _open_backend(self):
        if self.backend == "win32":
            return WindowsConsole()
        if self.backend == "msvcrt":
            return MsvcrtConsole()
        raise ValueError(f"unsupported TUI backend: {self.backend}")

    def _seed_intro(self) -> None:
        provider = str(self.target.config.get("provider_id") or "provider-unset")
        mode = str(self.target.config.get("mode") or "chat")
        self.state.transcript.append(
            TranscriptItem(
                role="system",
                text=f"AITools Companion started. provider={provider}, mode={mode}. Type /help for commands.",
            )
        )
        if self.debug_terminal:
            self.state.transcript.append(TranscriptItem(role="terminal", text=self._terminal_debug_text()))

    def _terminal_title(self) -> str:
        provider = str(self.target.config.get("provider_id") or "provider-unset")
        return f"AITools Companion - {provider}"

    def _terminal_debug_text(self) -> str:
        return build_terminal_debug_text(
            input_backend="companion_tui",
            event_backend=self.backend,
            backend_report=self.backend_report(self.backend),
            all_backends=self.availability_report(),
            include_encoding=False,
            include_env=False,
        )

    def _handle_console_event(self, event: ConsoleEvent) -> None:
        if event.kind == "resize":
            return
        if event.kind != "key":
            return
        self.state.key_events_seen += 1
        self.state.last_key = self._format_event(event)
        self._log("key", self.state.last_key)
        if event.ctrl:
            self._handle_ctrl_key(event)
            return
        if event.key == "char" and event.text:
            self._insert(event.text)
        elif event.key == "enter":
            self._submit_draft()
        elif event.key == "backspace":
            self._backspace()
        elif event.key == "delete":
            self._delete()
        elif event.key == "left":
            self.state.cursor = max(0, self.state.cursor - 1)
        elif event.key == "right":
            self.state.cursor = min(len(self.state.draft), self.state.cursor + 1)
        elif event.key == "home":
            self.state.cursor = 0
        elif event.key == "end":
            self.state.cursor = len(self.state.draft)
        elif event.key == "up":
            self._history(-1)
        elif event.key == "down":
            self._history(1)
        elif event.key == "escape":
            self._clear_draft()
        elif event.key == "error":
            self.state.status = "console input error"
            self._log("input_error", "reader stopped")
            self.state.transcript.append(
                TranscriptItem(
                    role="error",
                    text="Console input reader stopped. Restart with `build_and_run.bat cli --backend plain` for line input.",
                )
            )

    def _handle_ctrl_key(self, event: ConsoleEvent) -> None:
        key = event.key.lower()
        if key == "c":
            if self.state.draft:
                self._clear_draft()
                self.state.status = "draft cleared"
                return
            now = time.monotonic()
            if now - self.state.last_ctrl_c_at < 2.0:
                self.state.should_exit = True
            else:
                self.state.status = "press Ctrl+C again to quit"
                self.state.last_ctrl_c_at = now
        elif key == "d" and not self.state.draft:
            self.state.should_exit = True
        elif key == "u":
            self._clear_draft()
        elif key == "a":
            self.state.cursor = 0
        elif key == "e":
            self.state.cursor = len(self.state.draft)
        elif key == "l":
            self.state.transcript.clear()
            self.state.status = "transcript cleared"

    def _format_event(self, event: ConsoleEvent) -> str:
        mods = []
        if event.ctrl:
            mods.append("ctrl")
        if event.alt:
            mods.append("alt")
        if event.shift:
            mods.append("shift")
        prefix = "+".join(mods)
        key = event.key or "unknown"
        if event.text:
            key = f"{key}:{event.text[-8:]}"
        return f"{prefix + '+' if prefix else ''}{key}"

    def _insert(self, text: str) -> None:
        before = self.state.draft[: self.state.cursor]
        after = self.state.draft[self.state.cursor :]
        self.state.draft = before + text + after
        self.state.cursor += len(text)
        self.state.history_index = None
        self.state.status = "editing"

    def _backspace(self) -> None:
        if self.state.cursor <= 0:
            return
        self.state.draft = self.state.draft[: self.state.cursor - 1] + self.state.draft[self.state.cursor :]
        self.state.cursor -= 1

    def _delete(self) -> None:
        if self.state.cursor >= len(self.state.draft):
            return
        self.state.draft = self.state.draft[: self.state.cursor] + self.state.draft[self.state.cursor + 1 :]

    def _clear_draft(self) -> None:
        self.state.draft = ""
        self.state.cursor = 0
        self.state.history_index = None

    def _history(self, step: int) -> None:
        if not self.state.prompt_history:
            return
        if self.state.history_index is None:
            self.state.history_index = len(self.state.prompt_history)
        self.state.history_index = max(0, min(len(self.state.prompt_history), self.state.history_index + step))
        if self.state.history_index == len(self.state.prompt_history):
            self._clear_draft()
            return
        self.state.draft = self.state.prompt_history[self.state.history_index]
        self.state.cursor = len(self.state.draft)

    def _submit_draft(self) -> None:
        text = self.state.draft.strip()
        if not text:
            return
        self._clear_draft()
        if text in {"/exit", "/quit", "exit", "quit"}:
            self.state.should_exit = True
            return
        if text == "/help":
            self.state.transcript.append(TranscriptItem(role="help", text="\n".join(HELP_LINES)))
            self.state.status = "ready"
            return
        if text == "/status":
            self.state.transcript.append(TranscriptItem(role="status", text=self._status_text()))
            self.state.status = "ready"
            return
        if text == "/restart":
            self._restart()
            return
        if text == "/clear":
            self.state.transcript.clear()
            self.state.status = "transcript cleared"
            return
        if self.state.running:
            self.state.queued.append(text)
            self.state.status = f"queued {len(self.state.queued)} message(s)"
            return
        self._start_turn(text)

    def _start_turn(self, text: str) -> None:
        self._log("submit", text[:200])
        self.state.prompt_history.append(text)
        self.state.transcript.append(TranscriptItem(role="user", text=text))
        assistant = TranscriptItem(role="assistant", text="", status="working")
        self.state.transcript.append(assistant)
        self.state.active_assistant_index = len(self.state.transcript) - 1
        self.state.running = True
        self.state.status = "working"
        thread = threading.Thread(target=self._run_worker, args=(text,), name="companion-agent-turn", daemon=True)
        thread.start()

    def _restart(self) -> None:
        try:
            launched = launch_restart_bat()
        except Exception as exc:
            self.state.transcript.append(TranscriptItem(role="error", text=f"restart failed: {type(exc).__name__}: {exc}"))
            self.state.status = "restart failed"
            return
        self.state.transcript.append(
            TranscriptItem(role="status", text=f"Started Restart.bat\nscript: {launched.script_path}\npid: {launched.pid}")
        )
        self.state.status = "restart launched"
        self.state.restart_requested = True
        self.state.should_exit = True

    def _run_worker(self, text: str) -> None:
        try:
            self._log("turn_start", text[:200])
            result = self.run_turn(
                self.target,
                text,
                print_stream=False,
                stream_handler=lambda payload: self.worker_events.put(("stream", payload)),
            )
            self.worker_events.put(("done", result))
        except Exception as exc:
            self._log("turn_error", f"{type(exc).__name__}: {exc}")
            self.worker_events.put(("error", f"{type(exc).__name__}: {exc}"))

    def _drain_worker_events(self) -> None:
        while True:
            try:
                kind, payload = self.worker_events.get_nowait()
            except queue.Empty:
                break
            if kind == "stream":
                self._log("stream", self._summarize_payload(payload))
                self._handle_stream(payload)
            elif kind == "done":
                self._log("turn_done", self._summarize_payload(payload))
                self._finish_turn(payload)
            elif kind == "error":
                self._finish_turn({"response": str(payload), "error": True})

    def _drain_inbox(self) -> None:
        now = time.monotonic()
        if now - self.last_inbox_check < 0.5:
            return
        self.last_inbox_check = now
        try:
            notices = drain_companion_notices(config_path=self.target.config_path)
        except Exception as exc:
            self.state.transcript.append(
                TranscriptItem(role="error", text=f"companion inbox error: {type(exc).__name__}: {exc}")
            )
            self.state.status = "inbox error"
            return
        for notice in notices:
            text = format_companion_notice(notice)
            self.state.transcript.append(TranscriptItem(role="notice", text=text))
            if self.state.running:
                self.state.queued.append(text)
                self.state.status = f"queued {len(self.state.queued)} notice(s)"
                continue
            self._start_turn(text)

    def _handle_stream(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        event_type = str(payload.get("type") or "")
        if event_type == "node_message_delta":
            self._append_assistant_text(str(payload.get("delta") or ""))
        elif event_type == "node_message_done":
            self._set_assistant_text(str(payload.get("text") or ""))
        elif event_type in {"tool_call_start", "tool_call_end"}:
            name = str(payload.get("name") or "tool")
            status = str(payload.get("status") or event_type)
            self.state.transcript.append(TranscriptItem(role="tool", text=f"{name}: {status}"))

    def _finish_turn(self, result: object) -> None:
        response = ""
        is_error = False
        if isinstance(result, dict):
            response = str(result.get("response") or "")
            is_error = bool(result.get("error"))
        if response and not self._active_assistant_text():
            self._set_assistant_text(response)
        self._set_assistant_status("error" if is_error else "done")
        self.state.running = False
        self.state.status = "ready" if not is_error else "error"
        self.state.active_assistant_index = None
        if self.state.queued:
            next_text = self.state.queued.pop(0)
            self._start_turn(next_text)

    def _append_assistant_text(self, text: str) -> None:
        index = self.state.active_assistant_index
        if index is not None:
            self.state.transcript[index].text += text

    def _set_assistant_text(self, text: str) -> None:
        index = self.state.active_assistant_index
        if index is not None and text:
            self.state.transcript[index].text = text

    def _active_assistant_text(self) -> str:
        index = self.state.active_assistant_index
        if index is None:
            return ""
        return self.state.transcript[index].text

    def _set_assistant_status(self, status: str) -> None:
        index = self.state.active_assistant_index
        if index is not None:
            self.state.transcript[index].status = status

    def _status_text(self) -> str:
        fields = [
            ("graph", self.target.graph_id),
            ("provider", self.target.config.get("provider_id") or ""),
            ("mode", self.target.config.get("mode") or ""),
            ("thinking", self.target.config.get("thinking") or ""),
            ("reasoning", self.target.config.get("reasoning_effort") or ""),
            ("web_search", self.target.config.get("web_search") or ""),
            ("working_path", self.target.config.get("working_path") or ""),
            ("config", self.target.config_path),
            ("memory", self.target.memory_path),
            ("messages", self.target.messages_path),
        ]
        return "\n".join(f"{key}: {value}" for key, value in fields)

    def _render(self, screen: TerminalScreen) -> None:
        width, height = screen.size()
        screen.render(
            render_tui_text(
                target=self.target,
                state=self.state,
                backend=self.backend,
                started_at=self.started_at,
                log_path=self.log_path,
                spinner_index=self.spinner_index,
                width=width,
                height=height,
            )
        )

    def _summarize_payload(self, payload: object) -> str:
        if isinstance(payload, dict):
            parts = []
            for key in ("type", "status", "name", "response"):
                value = payload.get(key)
                if value:
                    parts.append(f"{key}={str(value)[:120]}")
            return ", ".join(parts) or str(payload)[:200]
        return str(payload)[:200]

    def _log(self, event: str, detail: str) -> None:
        if not self.log_path:
            return
        try:
            path = Path(self.log_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().isoformat(timespec="seconds")
            safe_detail = str(detail).replace("\r", "\\r").replace("\n", "\\n")
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"{timestamp}\t{event}\t{safe_detail}\n")
        except Exception:
            return
