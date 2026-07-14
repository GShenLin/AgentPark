from __future__ import annotations

import os
import threading
from typing import Any, Callable

from src.companion_inbox import drain_companion_notices
from src.companion_inbox import format_companion_notice
from src.companion_cli_window import hide_companion_cli_window
from src.cli_commands.companion_debug import build_terminal_debug_text
from src.cli_commands.companion_inbox_watcher import CompanionInboxWatcher
from src.cli_commands.companion_restart import launch_restart_bat
from src.cli_commands.companion_style import accent, error, field_line, muted, role_label


EXIT_COMMANDS = {"/exit", "/quit", "exit", "quit"}
HELP_TEXT = """Commands:
  /help    Show this help
  /status  Show companion runtime paths and provider config
  /restart Run the platform restart script and exit this CLI session
  /hidden  Hide this CLI window; use ToggleConsole.bat or folder right-click to show it
  /clear   Clear the terminal
  /exit    Quit

Enter submits a message. Ctrl+C cancels the current prompt; Ctrl+D exits."""

TurnRunner = Callable[[Any, str, bool], dict[str, Any]]


class PlainCompanionTerminal:
    def __init__(
        self,
        target: Any,
        *,
        debug_terminal: bool,
        run_turn: TurnRunner,
    ) -> None:
        self.target = target
        self.debug_terminal = debug_terminal
        self.run_turn = run_turn
        self.turn_lock = threading.Lock()

    def run(self) -> None:
        self._print_banner()
        if self.debug_terminal:
            self._print_block("terminal", self._terminal_debug_text())
        self._drain_inbox()
        watcher = CompanionInboxWatcher(self._drain_inbox)
        watcher.start()
        try:
            while True:
                try:
                    line = input("> ")
                except EOFError:
                    self._print_muted("exit")
                    break
                except KeyboardInterrupt:
                    self._print_muted("cancelled")
                    continue

                text = line.strip()
                if not text:
                    continue
                command = text.lower()
                if command in EXIT_COMMANDS:
                    break
                if command == "/help":
                    self._print_block("help", HELP_TEXT)
                    continue
                if command == "/status":
                    self._print_block("status", self._status_text())
                    continue
                if command == "/restart":
                    if self._restart():
                        return "restart"
                    continue
                if command == "/hidden":
                    self._hide_window()
                    continue
                if command == "/clear":
                    self._clear()
                    self._print_banner()
                    continue

                self._print_user_message(line)
                self._print_muted("working")
                try:
                    with self.turn_lock:
                        self.run_turn(self.target, line, print_stream=True)
                    self._drain_inbox()
                except KeyboardInterrupt:
                    self._print_error("interrupted")
                except Exception as exc:
                    self._print_error(f"{type(exc).__name__}: {exc}")
            return ""
        finally:
            watcher.stop()

    def _print_banner(self) -> None:
        provider = str(self.target.config.get("provider_id") or "provider-unset")
        model_mode = str(self.target.config.get("mode") or "chat")
        print("")
        print(accent("AgentPark Companion"))
        print(field_line("provider", provider))
        print(field_line("mode", model_mode))
        print(field_line("interface", "companion cli"))
        print(field_line("config", self.target.config_path))
        print(field_line("memory", self.target.memory_path))
        print(field_line("help", "/help"))
        print("")

    def _terminal_debug_text(self) -> str:
        return build_terminal_debug_text(input_backend="plain")

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

    def _print_user_message(self, text: str) -> None:
        self._print_block("user", text)

    def _print_block(self, title: str, body: str) -> None:
        print("")
        print(role_label(title))
        for line in str(body or "").splitlines() or [""]:
            print(f"  {line}")
        print("")

    def _print_muted(self, text: str) -> None:
        print(muted(f"[{text}]"), flush=True)

    def _print_error(self, text: str) -> None:
        stderr = __import__("sys").stderr
        print(error(f"[error] {text}", stream=stderr), file=stderr, flush=True)

    def _drain_inbox(self) -> None:
        try:
            notices = drain_companion_notices(config_path=self.target.config_path)
        except Exception as exc:
            self._print_error(f"companion inbox error: {type(exc).__name__}: {exc}")
            return
        for notice in notices:
            text = format_companion_notice(notice)
            self._print_block("notice", text)
            self._print_muted("working")
            try:
                with self.turn_lock:
                    self.run_turn(self.target, text, print_stream=True)
            except KeyboardInterrupt:
                self._print_error("interrupted")
            except Exception as exc:
                self._print_error(f"{type(exc).__name__}: {exc}")

    def _restart(self) -> bool:
        try:
            launched = launch_restart_bat()
        except Exception as exc:
            self._print_error(f"restart failed: {type(exc).__name__}: {exc}")
            return False
        label = launched.label or "restart script"
        self._print_block("status", f"Started {label}\nscript: {launched.script_path}\npid: {launched.pid}")
        return True

    def _hide_window(self) -> None:
        try:
            hide_companion_cli_window()
        except Exception as exc:
            self._print_error(f"hide failed: {type(exc).__name__}: {exc}")

    def _clear(self) -> None:
        os = __import__("os")
        command = "cls" if os.name == "nt" else "clear"
        os.system(command)
