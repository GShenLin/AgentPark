from __future__ import annotations

import os
import sys
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from nodes.agent_node import Node as AgentNode
from src.companion_paths import COMPANION_GRAPH_ID, COMPANION_NODE_ID, companion_node_config_path
from src.companion_cli_window import companion_cli_window_session
from src.cli_commands.companion_live_events import CompanionLiveEventReducer
from src.cli_commands.companion_markdown_render import render_markdown_lines
from src.cli_commands.companion_prompt import PromptCompanionTerminal
from src.cli_commands.companion_restart import RESTART_EXIT_CODE
from src.cli_commands.companion_style import error, muted, role_label
from src.cli_commands.companion_terminal import PlainCompanionTerminal
from src.cli_commands.companion_tool_render import render_tool_event_lines
from src.cli_commands.companion_tui import CompanionTui
from src.message_protocol import build_text_envelope
from src.web_backend import runtime_paths
from src.web_backend.node_config_errors import NodeConfigReadError
from src.web_backend.node_config_service import node_config_service
from src.web_backend.node_memory_store import append_node_memory_entry, append_node_tool_call_entry, ensure_node_memory_files


@dataclass(frozen=True)
class ChatTarget:
    graph_id: str
    node_id: str
    config_path: str
    config: dict[str, Any]
    memory_path: str
    messages_path: str


def run_chat(args) -> dict[str, Any]:
    target = resolve_chat_target(getattr(args, "config", ""))
    prompt = str(getattr(args, "message", "") or "")
    json_output = bool(getattr(args, "json", False))
    plain = bool(getattr(args, "plain", False))
    backend = str(getattr(args, "backend", "") or "").strip().lower()
    debug_terminal = bool(getattr(args, "debug_terminal", False))
    log_path = _default_log_path()

    if prompt:
        result = _run_one_turn(target, prompt, print_stream=not json_output)
        if json_output:
            return {"status": "success", **result}
        return {"status": "success", "_printed": True, **result}

    if json_output:
        raise ValueError("--json requires --message for chat")

    if plain and backend and backend != "plain":
        raise ValueError("--plain cannot be combined with --backend other than plain")
    if plain:
        backend = "plain"
    if not backend:
        backend = "auto"

    window_managed = str(os.environ.get("AGENTPARK_CLI_WINDOW_MANAGED") or "").strip() == "1"
    start_hidden = str(os.environ.get("AGENTPARK_CLI_START_HIDDEN") or "").strip() == "1"
    window_session = companion_cli_window_session(start_hidden=start_hidden) if window_managed else nullcontext()
    with window_session:
        session_result = _run_interactive_session(
            target,
            backend=backend,
            debug_terminal=debug_terminal,
            log_path=log_path,
        )
    payload = {"status": "success", "_printed": True, "graph": target.graph_id}
    if session_result == "restart":
        payload["_exit_code"] = RESTART_EXIT_CODE
    return payload


def _run_interactive_session(
    target: ChatTarget,
    *,
    backend: str,
    debug_terminal: bool,
    log_path: str,
) -> str:
    if backend == "plain":
        return PlainCompanionTerminal(target, debug_terminal=debug_terminal, run_turn=_run_one_turn).run() or ""
    if backend == "prompt":
        if not PromptCompanionTerminal.is_available():
            detail = PromptCompanionTerminal.availability_report()
            raise RuntimeError(f"prompt backend is not available in this terminal: {detail}")
        return PromptCompanionTerminal(target, debug_terminal=debug_terminal, run_turn=_run_one_turn).run() or ""
    if backend in {"msvcrt", "win32"}:
        if not CompanionTui.backend_available(backend):
            detail = CompanionTui.backend_report(backend)
            raise RuntimeError(f"{backend} TUI backend is not available in this terminal: {detail}")
        return CompanionTui(
            target,
            debug_terminal=debug_terminal,
            run_turn=_run_one_turn,
            backend=backend,
            log_path=log_path,
        ).run() or ""
    if backend == "auto":
        selected_backend = _select_interactive_backend()
        if not selected_backend:
            detail = _interactive_availability_report()
            raise RuntimeError(f"no interactive backend is available in this terminal: {detail}")
        return _run_selected_interactive_backend(
            target,
            selected_backend,
            debug_terminal=debug_terminal,
            log_path=log_path,
        ) or ""
    raise ValueError(f"unsupported chat backend: {backend}")


def _select_interactive_backend() -> str:
    if PromptCompanionTerminal.is_available():
        return "prompt"
    for backend in ("win32", "msvcrt"):
        if CompanionTui.backend_available(backend):
            return backend
    return ""


def _run_selected_interactive_backend(
    target: ChatTarget,
    backend: str,
    *,
    debug_terminal: bool,
    log_path: str,
) -> str:
    if backend == "prompt":
        return PromptCompanionTerminal(target, debug_terminal=debug_terminal, run_turn=_run_one_turn).run() or ""
    return CompanionTui(
        target,
        debug_terminal=debug_terminal,
        run_turn=_run_one_turn,
        backend=backend,
        log_path=log_path,
    ).run() or ""


def _interactive_availability_report() -> str:
    return f"prompt=({PromptCompanionTerminal.availability_report()}), tui=({CompanionTui.availability_report()})"


def _default_log_path() -> str:
    return os.path.join(runtime_paths._get_runtime_root(), ".runtime", "companion-cli.log")


def resolve_chat_target(config_path: object = "") -> ChatTarget:
    config_path = _resolve_companion_config_path(config_path)
    if not os.path.isfile(config_path):
        raise ValueError(f"companion config does not exist: {config_path}")
    try:
        cfg = node_config_service.read_strict(config_path)
    except NodeConfigReadError as exc:
        raise ValueError(str(exc)) from exc
    type_id = str(cfg.get("type_id") or "agent_node").strip() or "agent_node"
    if type_id != "agent_node":
        raise ValueError(f"companion config type_id must be agent_node: {config_path}")
    graph_id = _safe_id(cfg.get("graph_id"), COMPANION_GRAPH_ID)
    node_id = _safe_id(cfg.get("node_id"), COMPANION_NODE_ID)
    node_dir = os.path.dirname(config_path)
    return ChatTarget(
        graph_id=graph_id,
        node_id=node_id,
        config_path=config_path,
        config=cfg,
        memory_path=os.path.join(node_dir, "memory.md"),
        messages_path=os.path.join(node_dir, "messages.jsonl"),
    )


def _run_one_turn(
    target: ChatTarget,
    prompt: str,
    *,
    print_stream: bool,
    stream_handler=None,
) -> dict[str, Any]:
    latest_config = node_config_service.read_strict(target.config_path)
    target.config.clear()
    target.config.update(latest_config)
    ensure_node_memory_files(target.memory_path, target.messages_path)
    user_message = build_text_envelope(prompt, role="user")
    append_node_memory_entry(target.memory_path, target.messages_path, "user", user_message)

    printer = _StreamPrinter(
        enabled=print_stream,
        messages_path=target.messages_path,
        memory_path=target.memory_path,
        stream_handler=stream_handler,
    )
    result = AgentNode().on_input(
        user_message,
        {
            "graph_id": target.graph_id,
            "node_instance_id": target.node_id,
            "memory_path": target.memory_path,
            "messages_path": target.messages_path,
            "stream_callback": printer.handle,
            **_context_config(target.config),
        },
    )
    assistant_message = _assistant_message_from_result(result)
    append_node_memory_entry(target.memory_path, target.messages_path, "assistant", assistant_message)
    final_text = str((result or {}).get("display") or "")
    printer.finish(final_text)
    return {"graph": target.graph_id, "response": final_text}


def _resolve_companion_config_path(config_path: object = "") -> str:
    text = str(config_path or "").strip()
    if text:
        return os.path.abspath(text)
    return companion_node_config_path(runtime_paths._get_graphs_dir())


def _safe_id(value: object, default: str) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in text)
    return safe.strip("_") or default


def _context_config(config: dict[str, Any]) -> dict[str, Any]:
    blocked = {"schemaVersion", "node_id", "agent_id", "graph_id", "type_id", "name", "state"}
    return {key: value for key, value in config.items() if isinstance(key, str) and key not in blocked}


def _assistant_message_from_result(result: object) -> dict[str, Any]:
    if isinstance(result, dict):
        routes = result.get("routes")
        if isinstance(routes, list):
            for item in routes:
                if isinstance(item, dict) and item.get("output_index") == 0 and item.get("payload") is not None:
                    return item.get("payload")
        if result.get("display") is not None:
            return build_text_envelope(result.get("display"), role="assistant")
    return build_text_envelope(result, role="assistant")


class _StreamPrinter:
    def __init__(self, *, enabled: bool, memory_path: str, messages_path: str, stream_handler=None) -> None:
        self.enabled = enabled
        self.memory_path = memory_path
        self.messages_path = messages_path
        self.stream_handler = stream_handler
        self.live_events = CompanionLiveEventReducer()
        self.printed_any = False
        self.active_stream_channel = ""

    def handle(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return
        if callable(self.stream_handler):
            self.stream_handler(payload)
        event_type = str(payload.get("type") or "").strip()
        if event_type in {"tool_call_start", "tool_call_end"}:
            try:
                append_node_tool_call_entry(self.memory_path, self.messages_path, payload)
            except Exception as exc:
                self._print_line(
                    error(f"[tool-history-error] {type(exc).__name__}: {exc}", stream=sys.stderr),
                    stream=sys.stderr,
                )
        actions = self.live_events.consume(payload)
        if not self.enabled:
            return
        for action in actions:
            if action.kind == "delta":
                self._write_stream_delta(action.channel, action.text)
            elif action.kind == "close":
                self._close_live_stream()
            elif action.kind == "activity":
                self._close_live_stream()
                print(muted(f"activity {action.text}"), flush=True)
                self.printed_any = True
            elif action.kind == "tool" and action.event is not None:
                self._close_live_stream()
                self._print_tool_event(action.event)
            elif action.kind == "server_tool" and action.event is not None:
                self._close_live_stream()
                self._print_server_tool_event(action.event)

    def finish(self, final_text: str) -> None:
        if not self.enabled:
            return
        candidate = str(final_text or self.live_events.answer_text or "")
        if self.active_stream_channel:
            if candidate.startswith(self.live_events.answer_text):
                self._write_stream_delta("assistant", candidate[len(self.live_events.answer_text) :])
            self._close_live_stream()
            return
        if candidate and not self.live_events.answer_text:
            self._print_assistant_block(candidate)
            self.printed_any = True
            return
        if self.printed_any:
            print("", flush=True)

    def _write_stream_delta(self, channel: str, delta: str) -> None:
        if not delta:
            return
        prefix = ""
        if self.active_stream_channel != channel:
            if self.active_stream_channel:
                prefix = "\n"
            prefix += f"\n{role_label(channel)}\n  "
            self.active_stream_channel = channel
        rendered_delta = delta.replace("\n", "\n  ")
        sys.stdout.write(prefix + rendered_delta)
        sys.stdout.flush()
        self.printed_any = True

    def _close_live_stream(self) -> None:
        if not self.active_stream_channel:
            return
        sys.stdout.write("\n")
        sys.stdout.flush()
        self.active_stream_channel = ""

    def _print_assistant_block(self, text: str) -> None:
        print("")
        print(role_label("assistant"))
        for line in render_markdown_lines(text, indent="  "):
            print(line, flush=True)

    def _print_tool_event(self, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        if self.printed_any:
            print("", flush=True)
        for line in render_tool_event_lines(payload):
            print(muted(line), flush=True)
        self.printed_any = False

    def _print_server_tool_event(self, payload: dict[str, Any]) -> None:
        tool_type = str(payload.get("tool_type") or "server_tool").strip() or "server_tool"
        status = str(payload.get("status") or "in_progress").strip() or "in_progress"
        print(muted(f"server tool {tool_type}: {status}"), flush=True)
        self.printed_any = True

    def _print_line(self, text: str, *, stream=None) -> None:
        if not self.enabled:
            return
        print(text, file=stream or sys.stdout, flush=True)
