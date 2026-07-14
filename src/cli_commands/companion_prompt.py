from __future__ import annotations

import os
import sys
import threading
from dataclasses import dataclass
from typing import Any, Callable

from src.companion_inbox import drain_companion_notices
from src.companion_inbox import format_companion_notice
from src.companion_cli_window import hide_companion_cli_window
from src.cli_commands.companion_debug import build_terminal_debug_text
from src.cli_commands.companion_choice_menu import run_choice_menu
from src.cli_commands.companion_config_menus import select_provider, select_reasoning, toggle_capability
from src.cli_commands.companion_inbox_watcher import CompanionInboxWatcher
from src.cli_commands.companion_prompt_input import CompanionPromptInputBridge
from src.cli_commands.companion_prompt_live import PromptLiveTranscript
from src.cli_commands.companion_prompt_turns import PromptTurnCoordinator
from src.cli_commands.companion_restart import launch_restart_bat
from src.cli_commands.companion_style import accent, error, field_line, muted, role_label
from src.web_backend.node_config_service import node_config_service


EXIT_COMMANDS = {"/exit", "/quit", "exit", "quit"}
COMMANDS = [
    ("/help", "Show available companion commands"),
    ("/status", "Show provider, config, memory, and runtime paths"),
    ("/restart", "Run the platform restart script and exit this CLI session"),
    ("/provider", "Select the Companion provider"),
    ("/resoning", "Select the reasoning effort"),
    ("/tool", "Enable or remove a Companion tool"),
    ("/mcp", "Enable or remove a Companion MCP server"),
    ("/skill", "Enable or remove a Companion skill"),
    ("/hidden", "Hide this CLI window"),
    ("/clear", "Clear the terminal transcript"),
    ("/exit", "Quit the companion CLI"),
]
HELP_TEXT = """Commands:
  /help    Show this help
  /status  Show companion runtime paths and provider config
  /restart Run the platform restart script and exit this CLI session
  /provider Select the Companion provider with Up/Down and Enter
  /resoning Select reasoning effort with Up/Down and Enter
  /tool    Enable or remove one tool with Up/Down and Enter
  /mcp     Enable or remove one MCP server with Up/Down and Enter
  /skill   Enable or remove one skill with Up/Down and Enter
  /hidden  Hide this CLI window; use ToggleConsole.bat or folder right-click to show it
  /clear   Clear the terminal
  /exit    Quit

Enter submits a message. Ctrl+C cancels the current prompt; Ctrl+D exits."""

TurnRunner = Callable[[Any, str, bool], dict[str, Any]]


@dataclass(frozen=True)
class SlashCommand:
    name: str
    description: str


class SlashCommandCompleter:
    def __init__(self, commands: list[tuple[str, str]]) -> None:
        self.commands = [SlashCommand(name=name, description=description) for name, description in commands]

    def get_completions(self, document, complete_event):
        from prompt_toolkit.completion import Completion

        yield from self._iter_completions(document, Completion)

    async def get_completions_async(self, document, complete_event):
        from prompt_toolkit.completion import Completion

        for completion in self._iter_completions(document, Completion):
            yield completion

    def _iter_completions(self, document, completion_type):
        word = self._slash_word_at_cursor(document.text_before_cursor)
        if word is None:
            return
        typed = word[1:].lower()
        for command in self.commands:
            command_name = command.name[1:]
            if typed and not command_name.lower().startswith(typed):
                continue
            yield completion_type(
                command.name,
                start_position=-len(word),
                display=command.name,
                display_meta=command.description,
            )

    def _slash_word_at_cursor(self, text_before_cursor: str) -> str | None:
        first_line = text_before_cursor.splitlines()[0] if text_before_cursor.splitlines() else text_before_cursor
        if "\n" in text_before_cursor:
            return None
        if not first_line.startswith("/"):
            return None
        token = first_line.split(maxsplit=1)[0]
        if first_line.startswith("/ ") or "/" in token[1:]:
            return None
        if len(first_line) > len(token):
            return None
        return token


class PromptCompanionTerminal:
    backend_name = "prompt"

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
        self.config_signature = self._target_config_signature()
        self.live_transcript: PromptLiveTranscript | None = None
        input_bridge = CompanionPromptInputBridge(target)
        self.turns = PromptTurnCoordinator(
            target,
            run_turn=run_turn,
            turn_lock=self.turn_lock,
            print_user=self._print_user_message,
            print_status=self._print_muted,
            print_error=self._print_error,
            after_turn=self._after_turn,
            begin_turn=input_bridge.begin_turn,
            submit_mid_turn=input_bridge.submit_mid_turn,
            finish_turn=input_bridge.finish_turn,
        )

    @classmethod
    def is_available(cls) -> bool:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            return False
        try:
            import prompt_toolkit  # noqa: F401

            return True
        except Exception:
            return False

    @classmethod
    def availability_report(cls) -> str:
        try:
            import prompt_toolkit

            version = getattr(prompt_toolkit, "__version__", "unknown")
            import_status = f"prompt_toolkit={version}"
        except Exception as exc:
            import_status = f"prompt_toolkit_error={type(exc).__name__}: {exc}"
        return (
            f"stdin_isatty={sys.stdin.isatty()}, stdout_isatty={sys.stdout.isatty()}, "
            f"stdin_encoding={getattr(sys.stdin, 'encoding', '')}, "
            f"stdout_encoding={getattr(sys.stdout, 'encoding', '')}, {import_status}"
        )

    def run(self) -> None:
        PromptSession, Style = self._load_prompt_toolkit()
        session = PromptSession(
            completer=SlashCommandCompleter(COMMANDS),
            complete_while_typing=True,
            bottom_toolbar=self._toolbar,
            erase_when_done=True,
            reserve_space_for_menu=8,
            style=Style.from_dict(
                {
                    "bottom-toolbar": "reverse",
                    "live": "#d1d5db",
                    "prompt": "ansicyan bold",
                    "bottom-toolbar.text": "bg:#111827 #d1d5db",
                    "completion-menu.completion": "bg:#1f2937 #d1d5db",
                    "completion-menu.completion.current": "bg:#2563eb #ffffff bold",
                    "completion-menu.meta.completion": "bg:#111827 #9ca3af",
                    "completion-menu.meta.completion.current": "bg:#1d4ed8 #ffffff",
                }
            ),
        )
        self.live_transcript = PromptLiveTranscript(session.app.invalidate)
        self.turns.set_stream_handler(self.live_transcript.handle)
        self._print_banner()
        if self.debug_terminal:
            self._print_block("terminal", self._terminal_debug_text())

        self._drain_inbox()
        watcher = CompanionInboxWatcher(self._drain_inbox)
        watcher.start()
        try:
            with _patch_prompt_stdout():
                result = self._run_prompt_loop(session)
                if result == "restart":
                    return result
            return ""
        finally:
            watcher.stop()

    def _run_prompt_loop(self, session) -> str:
        while True:
            try:
                message = (
                    self.live_transcript.prompt_message
                    if self.live_transcript is not None
                    else [("class:prompt", "> ")]
                )
                line = session.prompt(message)
            except EOFError:
                if self.turns.running:
                    self._print_muted("waiting for current turn before exit")
                    self.turns.wait_until_idle()
                self._print_muted("exit")
                return ""
            except KeyboardInterrupt:
                self._print_muted("cancelled")
                continue

            text = line.strip()
            if not text:
                continue
            command = text.lower()
            if command in EXIT_COMMANDS:
                if self.turns.running:
                    self._print_muted("current turn is still working")
                    continue
                return ""
            if command == "/help":
                self._print_block("help", HELP_TEXT)
                continue
            if command == "/status":
                self._print_block("status", self._status_text())
                continue
            if command == "/restart":
                if self.turns.running:
                    self._print_muted("current turn is still working")
                    continue
                if self._restart():
                    return "restart"
                continue
            if command == "/hidden":
                self._hide_window()
                continue
            if command in {"/provider", "/resoning", "/reasoning", "/tool", "/mcp", "/skill"}:
                if self.turns.running:
                    self._print_muted("configuration can be changed after the current turn")
                    continue
                self._run_config_command(command)
                continue
            if command == "/clear":
                self._clear()
                self._print_banner()
                continue
            self.turns.submit(line)

    def _run_config_command(self, command: str) -> None:
        if command == "/provider":
            self._select_provider()
        elif command in {"/resoning", "/reasoning"}:
            self._select_reasoning()
        else:
            self._toggle_capability(command[1:])

    def _after_turn(self) -> None:
        if self.live_transcript is not None:
            transcript = self.live_transcript.commit()
            if transcript:
                print(transcript, flush=True)
        self._drain_inbox()

    def _load_prompt_toolkit(self):
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.styles import Style
        except Exception as exc:
            raise RuntimeError(f"prompt backend is unavailable: {type(exc).__name__}: {exc}") from exc
        return PromptSession, Style

    def _select_provider(self) -> None:
        if select_provider(self.target, self._run_choice_menu, self._print_error):
            self.config_signature = self._target_config_signature()

    def _select_reasoning(self) -> None:
        if select_reasoning(self.target, self._run_choice_menu, self._print_error):
            self.config_signature = self._target_config_signature()

    def _toggle_capability(self, kind: str) -> None:
        if toggle_capability(self.target, kind, self._run_choice_menu, self._print_error):
            self.config_signature = self._target_config_signature()

    def _run_choice_menu(
        self,
        *,
        title: str,
        text: str,
        choices: list[tuple[str, str]],
        default: str,
        checked: set[str] | None = None,
    ) -> str | None:
        return run_choice_menu(
            title=title,
            text=text,
            choices=choices,
            default=default,
            checked=checked,
        )

    def _toolbar(self) -> str:
        self._refresh_target_config()
        provider = str(self.target.config.get("provider_id") or "provider-unset")
        reasoning = str(self.target.config.get("reasoning_effort") or "").strip() or "-"
        working_path = str(self.target.config.get("working_path") or "").strip() or "-"
        return f" provider: {provider} | reasoning: {reasoning} | WorkingPath: {working_path} "

    def _refresh_target_config(self) -> None:
        signature = self._target_config_signature()
        if signature == self.config_signature:
            return
        latest_config = node_config_service.read_strict(self.target.config_path)
        self.target.config.clear()
        self.target.config.update(latest_config)
        self.config_signature = signature

    def _target_config_signature(self) -> tuple[int, int, int]:
        stat = os.stat(self.target.config_path)
        return stat.st_mtime_ns, stat.st_size, stat.st_ino

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
        return build_terminal_debug_text(
            input_backend="prompt",
            backend_report=self.availability_report(),
        )

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
        print(error(f"[error] {text}", stream=sys.stderr), file=sys.stderr, flush=True)

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
        os.system("cls" if os.name == "nt" else "clear")


def _patch_prompt_stdout():
    from prompt_toolkit.patch_stdout import patch_stdout

    return patch_stdout(raw=True)
