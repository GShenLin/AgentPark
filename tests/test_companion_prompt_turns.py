from __future__ import annotations

import threading
from types import SimpleNamespace

from src.cli_commands.companion_prompt import PromptCompanionTerminal
from src.cli_commands.companion_prompt_input import CompanionPromptInputBridge
from src.cli_commands.companion_prompt_turns import PromptTurnCoordinator
from src.message_protocol import envelope_text
from src.web_backend.state_store import (
    _consume_node_mid_turn_user_inputs,
    _read_json_dict,
    _write_json_dict,
)


def test_prompt_stdout_patch_uses_public_supported_options(monkeypatch):
    import contextlib
    import prompt_toolkit.patch_stdout as patch_stdout_module
    import src.cli_commands.companion_prompt as companion_prompt

    calls = []

    def fake_patch_stdout(**kwargs):
        calls.append(kwargs)
        return contextlib.nullcontext()

    monkeypatch.setattr(patch_stdout_module, "patch_stdout", fake_patch_stdout)

    with companion_prompt._patch_prompt_stdout():
        pass

    assert calls == [{"raw": True}]


def test_prompt_turn_coordinator_submits_working_input_to_mid_turn_channel():
    turn_started = threading.Event()
    release_turn = threading.Event()
    run_messages: list[str] = []
    mid_turn_messages: list[str] = []

    def run_turn(_target, message, *, print_stream):
        assert print_stream is True
        run_messages.append(message)
        turn_started.set()
        assert release_turn.wait(timeout=2)
        return {}

    coordinator = PromptTurnCoordinator(
        object(),
        run_turn=run_turn,
        turn_lock=threading.Lock(),
        print_user=lambda _text: None,
        print_status=lambda _text: None,
        print_error=lambda _text: None,
        after_turn=lambda: None,
        begin_turn=lambda _text: None,
        submit_mid_turn=mid_turn_messages.append,
        finish_turn=lambda: None,
    )

    coordinator.submit("first")
    assert turn_started.wait(timeout=2)
    coordinator.submit("new constraint")
    release_turn.set()

    assert coordinator.wait_until_idle(timeout=2)
    assert run_messages == ["first"]
    assert mid_turn_messages == ["new constraint"]


def test_prompt_turn_coordinator_routes_events_to_live_handler_without_direct_printing():
    run_options = []
    received = []

    def run_turn(_target, _message, **kwargs):
        run_options.append(kwargs)
        kwargs["stream_handler"]({"type": "node_thinking_delta", "delta": "Checking", "text": "Checking"})
        return {}

    coordinator = PromptTurnCoordinator(
        object(),
        run_turn=run_turn,
        turn_lock=threading.Lock(),
        print_user=lambda _text: None,
        print_status=lambda _text: None,
        print_error=lambda _text: None,
        after_turn=lambda: None,
        begin_turn=lambda _text: None,
        submit_mid_turn=lambda _text: None,
        finish_turn=lambda: None,
    )
    coordinator.set_stream_handler(received.append)

    coordinator.submit("first")

    assert coordinator.wait_until_idle(timeout=2)
    assert run_options == [{"print_stream": False, "stream_handler": received.append}]
    assert received == [{"type": "node_thinking_delta", "delta": "Checking", "text": "Checking"}]


def test_prompt_loop_requests_next_input_while_companion_is_working(tmp_path):
    config_path = tmp_path / "config.json"
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    _write_json_dict(
        str(config_path),
        {"node_id": "Companion", "graph_id": "Companion", "type_id": "agent_node", "state": "idle"},
    )
    next_prompt_requested = threading.Event()

    def run_turn(_target, _message, *, print_stream):
        assert print_stream is True
        assert next_prompt_requested.wait(timeout=2)
        return {}

    target = SimpleNamespace(
        node_id="Companion",
        graph_id="Companion",
        config_path=str(config_path),
        config={},
        memory_path=str(memory_path),
        messages_path=str(messages_path),
    )
    terminal = PromptCompanionTerminal(target, debug_terminal=False, run_turn=run_turn)

    class Session:
        prompt_count = 0

        def prompt(self, _prompt):
            self.prompt_count += 1
            if self.prompt_count == 1:
                return "start"
            next_prompt_requested.set()
            raise EOFError

    assert terminal._run_prompt_loop(Session()) == ""
    assert next_prompt_requested.is_set()
    assert terminal.turns.wait_until_idle(timeout=2)


def test_prompt_input_bridge_uses_agent_node_mid_turn_input_contract(tmp_path):
    config_path = tmp_path / "config.json"
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    _write_json_dict(
        str(config_path),
        {
            "node_id": "Companion",
            "graph_id": "Companion",
            "type_id": "agent_node",
            "state": "idle",
            "pending": [],
        },
    )
    target = SimpleNamespace(
        node_id="Companion",
        config_path=str(config_path),
        memory_path=str(memory_path),
        messages_path=str(messages_path),
    )
    bridge = CompanionPromptInputBridge(target)

    bridge.begin_turn("start")
    bridge.submit_mid_turn("use the new constraint")
    consumed = _consume_node_mid_turn_user_inputs(str(config_path))
    bridge.finish_turn()

    assert len(consumed) == 1
    assert consumed[0]["source"] == "emit"
    assert envelope_text(consumed[0]["payload"]) == "use the new constraint"
    assert _read_json_dict(str(config_path))["state"] == "idle"
    assert "use the new constraint" in messages_path.read_text(encoding="utf-8")
