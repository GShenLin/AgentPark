from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Callable

from src.cli_commands.companion_debug import build_terminal_debug_text
from src.cli_commands.companion_restart import launch_restart_bat
from src.cli_commands.companion_style import accent, error, field_line, muted, role_label


EXIT_COMMANDS = {"/exit", "/quit", "exit", "quit"}
COMMANDS = [
    ("/help", "Show available companion commands"),
    ("/status", "Show provider, config, memory, and runtime paths"),
    ("/restart", "Run Restart.bat and exit this CLI session"),
    ("/clear", "Clear the terminal transcript"),
    ("/exit", "Quit the companion CLI"),
]
HELP_TEXT = """Commands:
  /help    Show this help
  /status  Show companion runtime paths and provider config
  /restart Run Restart.bat and exit this CLI session
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
        self.turn_count = 0

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
            reserve_space_for_menu=8,
            style=Style.from_dict(
                {
                    "bottom-toolbar": "reverse",
                    "prompt": "ansicyan bold",
                    "bottom-toolbar.text": "bg:#111827 #d1d5db",
                    "completion-menu.completion": "bg:#1f2937 #d1d5db",
                    "completion-menu.completion.current": "bg:#2563eb #ffffff bold",
                    "completion-menu.meta.completion": "bg:#111827 #9ca3af",
                    "completion-menu.meta.completion.current": "bg:#1d4ed8 #ffffff",
                }
            ),
        )
        self._print_banner()
        if self.debug_terminal:
            self._print_block("terminal", self._terminal_debug_text())

        while True:
            try:
                line = session.prompt([("class:prompt", "> ")])
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
            if command == "/clear":
                self._clear()
                self._print_banner()
                continue

            self._print_user_message(line)
            self._print_muted("working")
            try:
                self.run_turn(self.target, line, print_stream=True)
                self.turn_count += 1
            except KeyboardInterrupt:
                self._print_error("interrupted")
            except Exception as exc:
                self._print_error(f"{type(exc).__name__}: {exc}")
        return ""

    def _load_prompt_toolkit(self):
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.styles import Style
        except Exception as exc:
            raise RuntimeError(f"prompt backend is unavailable: {type(exc).__name__}: {exc}") from exc
        return PromptSession, Style

    def _toolbar(self) -> str:
        provider = str(self.target.config.get("provider_id") or "provider-unset")
        mode = str(self.target.config.get("mode") or "chat")
        reasoning = str(self.target.config.get("reasoning_effort") or "")
        return f" AITools Companion | provider {provider} | mode {mode} | reasoning {reasoning} | turns {self.turn_count} "

    def _print_banner(self) -> None:
        provider = str(self.target.config.get("provider_id") or "provider-unset")
        model_mode = str(self.target.config.get("mode") or "chat")
        print("")
        print(accent("AITools Companion"))
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

    def _restart(self) -> bool:
        try:
            launched = launch_restart_bat()
        except Exception as exc:
            self._print_error(f"restart failed: {type(exc).__name__}: {exc}")
            return False
        self._print_block("status", f"Started Restart.bat\nscript: {launched.script_path}\npid: {launched.pid}")
        return True

    def _clear(self) -> None:
        os.system("cls" if os.name == "nt" else "clear")
