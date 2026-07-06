import json
import os

from src.cli import main


def _write_config(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_cli_capabilities_list_and_enable_offline(monkeypatch, tmp_path, capsys):
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    config_path = graphs_dir / "g1" / "n1" / "config.json"
    _write_config(config_path, {"node_id": "n1", "graph_id": "g1", "tools": []})
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))

    assert main(["capabilities", "list", "--graph", "g1", "--node", "n1", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["status"] == "success"
    assert "tool" in listed["capabilities"]

    assert (
        main(
            [
                "capabilities",
                "enable",
                "--graph",
                "g1",
                "--node",
                "n1",
                "--kind",
                "tool",
                "--name",
                "file_read_tools",
                "--json",
            ]
        )
        == 0
    )
    enabled = json.loads(capsys.readouterr().out)
    assert enabled["changed_fields"] == ["tools"]
    assert json.loads(config_path.read_text(encoding="utf-8"))["tools"] == ["file_read_tools"]


def test_cli_capabilities_list_refresh_invalidates_discovery_cache(monkeypatch, tmp_path, capsys):
    import src.cli_commands.capabilities as capabilities_command
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    config_path = graphs_dir / "g1" / "n1" / "config.json"
    _write_config(config_path, {"node_id": "n1", "graph_id": "g1", "tools": []})
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    calls = {"count": 0}

    def fake_invalidate():
        calls["count"] += 1

    monkeypatch.setattr(capabilities_command, "invalidate_discovery_cache", fake_invalidate)

    assert main(["capabilities", "list", "--graph", "g1", "--node", "n1", "--refresh", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert calls["count"] == 1
    assert payload["status"] == "success"


def test_cli_doctor_reports_corrupt_node_config(monkeypatch, tmp_path, capsys):
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    config_path = graphs_dir / "g1" / "n1" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("{bad", encoding="utf-8")
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))

    exit_code = main(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    node_checks = [item for item in payload["checks"] if item["name"] == "node_config:g1/n1"]

    assert exit_code == 1
    assert payload["status"] == "error"
    assert node_checks
    assert "invalid JSON" in node_checks[0]["detail"]


def test_cli_doctor_reports_corrupt_graph_config(monkeypatch, tmp_path, capsys):
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    config_path = graphs_dir / "g1" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))

    exit_code = main(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    graph_checks = [item for item in payload["checks"] if item["name"] == "graph_config:g1"]

    assert exit_code == 1
    assert payload["status"] == "error"
    assert graph_checks
    assert "JSON object" in graph_checks[0]["detail"]


def test_cli_chat_uses_companion_config_and_persists_messages(monkeypatch, tmp_path, capsys):
    import src.cli_commands.chat as chat_command
    from src.web_backend import runtime_paths

    config_path = tmp_path / "memories" / "companion" / "config.json"
    _write_config(
        config_path,
        {
            "node_id": "companion",
            "graph_id": "companion",
            "type_id": "agent_node",
            "provider_id": "unit-provider",
            "tools": ["file_read_tools"],
            "working_path": str(tmp_path),
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))

    class DummyAgentNode:
        def on_input(self, message, context):
            assert context["graph_id"] == "companion"
            assert context["node_instance_id"] == "companion"
            assert context["memory_path"] == str(tmp_path / "memories" / "companion" / "memory.md")
            assert context["messages_path"] == str(tmp_path / "memories" / "companion" / "messages.jsonl")
            assert context["provider_id"] == "unit-provider"
            assert context["tools"] == ["file_read_tools"]
            assert context["working_path"] == str(tmp_path)
            assert message["role"] == "user"
            callback = context.get("stream_callback")
            if callable(callback):
                callback({"type": "node_message_delta", "delta": "pong", "text": "pong"})
                callback({"type": "node_message_done", "text": "pong"})
            return {
                "display": "pong",
                "routes": [
                    {
                        "output_index": 0,
                        "payload": {"role": "assistant", "parts": [{"type": "text", "text": "pong"}]},
                    }
                ],
            }

    monkeypatch.setattr(chat_command, "AgentNode", lambda: DummyAgentNode())

    exit_code = main(["chat", "--message", "ping"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "pong" in output
    node_dir = tmp_path / "memories" / "companion"
    records = [
        json.loads(line)
        for line in (node_dir / "messages.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [item["role"] for item in records] == ["user", "assistant"]
    assert records[0]["parts"][0]["text"] == "ping"
    assert records[1]["parts"][0]["text"] == "pong"


def test_cli_chat_renders_assistant_markdown(monkeypatch, tmp_path, capsys):
    import src.cli_commands.chat as chat_command
    from src.web_backend import runtime_paths

    config_path = tmp_path / "memories" / "companion" / "config.json"
    _write_config(
        config_path,
        {
            "node_id": "companion",
            "graph_id": "companion",
            "type_id": "agent_node",
            "provider_id": "unit-provider",
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setenv("AGENTPARK_COLOR", "1")

    markdown_text = "# Plan\n- inspect `code`\n```py\nprint(1)\n```"

    class DummyAgentNode:
        def on_input(self, message, context):
            callback = context.get("stream_callback")
            if callable(callback):
                callback({"type": "node_message_delta", "delta": markdown_text, "text": markdown_text})
                callback({"type": "node_message_done", "text": markdown_text})
            return {
                "display": markdown_text,
                "routes": [
                    {
                        "output_index": 0,
                        "payload": {"role": "assistant", "parts": [{"type": "text", "text": markdown_text}]},
                    }
                ],
            }

    monkeypatch.setattr(chat_command, "AgentNode", lambda: DummyAgentNode())

    exit_code = main(["chat", "--message", "render markdown"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "> Plan" in output
    assert "- inspect" in output
    assert "code py" in output
    assert "print(1)" in output
    assert "# Plan" not in output


def test_cli_chat_reports_missing_companion_config(tmp_path, capsys):
    missing_path = tmp_path / "memories" / "companion" / "config.json"

    exit_code = main(["chat", "--config", str(missing_path), "--message", "ping"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "companion config does not exist" in output


def test_cli_chat_interactive_commands_render_shell(monkeypatch, tmp_path, capsys):
    from src.web_backend import runtime_paths

    config_path = tmp_path / "memories" / "companion" / "config.json"
    _write_config(
        config_path,
        {
            "graph_id": "companion",
            "type_id": "agent_node",
            "provider_id": "unit-provider",
            "mode": "chat",
            "thinking": "disabled",
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    inputs = iter(["/status", "/help", "/exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    exit_code = main(["chat", "--plain"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "AgentPark Companion" in output
    assert "provider: unit-provider" in output
    assert "status" in output
    assert "Commands:" in output


def test_cli_chat_debug_reports_basic_input_backend(monkeypatch, tmp_path, capsys):
    from src.web_backend import runtime_paths

    config_path = tmp_path / "memories" / "companion" / "config.json"
    _write_config(
        config_path,
        {
            "graph_id": "companion",
            "type_id": "agent_node",
            "provider_id": "unit-provider",
            "mode": "chat",
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    inputs = iter(["/exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    exit_code = main(["chat", "--plain", "--debug-terminal"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "terminal" in output
    assert "input_backend: plain" in output


def test_cli_chat_default_backend_reports_unavailable(monkeypatch, tmp_path, capsys):
    import src.cli_commands.chat as chat_command
    from src.web_backend import runtime_paths

    config_path = tmp_path / "memories" / "companion" / "config.json"
    _write_config(
        config_path,
        {
            "graph_id": "companion",
            "type_id": "agent_node",
            "provider_id": "unit-provider",
            "mode": "chat",
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    monkeypatch.setattr(chat_command.PromptCompanionTerminal, "is_available", classmethod(lambda cls: False))
    monkeypatch.setattr(chat_command.PromptCompanionTerminal, "availability_report", classmethod(lambda cls: "no prompt"))
    monkeypatch.setattr(chat_command.CompanionTui, "backend_available", classmethod(lambda cls, backend: False))
    monkeypatch.setattr(chat_command.CompanionTui, "availability_report", classmethod(lambda cls: "not a console"))

    exit_code = main(["chat"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "no interactive backend is available" in output
    assert "no prompt" in output
    assert "not a console" in output


def test_cli_chat_auto_backend_selects_prompt(monkeypatch, tmp_path):
    import src.cli_commands.chat as chat_command
    from src.web_backend import runtime_paths

    config_path = tmp_path / "memories" / "companion" / "config.json"
    _write_config(
        config_path,
        {
            "graph_id": "companion",
            "type_id": "agent_node",
            "provider_id": "unit-provider",
            "mode": "chat",
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    calls = []

    class DummyPrompt:
        @classmethod
        def is_available(cls):
            return True

        @classmethod
        def availability_report(cls):
            return "available"

        def __init__(self, target, *, debug_terminal, run_turn):
            calls.append((target.graph_id, debug_terminal))

        def run(self):
            return None

    monkeypatch.setattr(chat_command, "PromptCompanionTerminal", DummyPrompt)

    exit_code = main(["chat"])

    assert exit_code == 0
    assert calls == [("companion", False)]


def test_cli_chat_auto_backend_uses_tui_when_prompt_unavailable(monkeypatch, tmp_path):
    import src.cli_commands.chat as chat_command
    from src.web_backend import runtime_paths

    config_path = tmp_path / "memories" / "companion" / "config.json"
    _write_config(
        config_path,
        {
            "graph_id": "companion",
            "type_id": "agent_node",
            "provider_id": "unit-provider",
            "mode": "chat",
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    calls = []

    class DummyPrompt:
        @classmethod
        def is_available(cls):
            return False

        @classmethod
        def availability_report(cls):
            return "prompt unavailable"

    class DummyTui:
        @classmethod
        def backend_available(cls, backend):
            return backend == "win32"

        @classmethod
        def availability_report(cls):
            return "available"

        def __init__(self, target, *, debug_terminal, run_turn, backend, log_path):
            calls.append((target.graph_id, debug_terminal, backend))

        def run(self):
            return None

    monkeypatch.setattr(chat_command, "PromptCompanionTerminal", DummyPrompt)
    monkeypatch.setattr(chat_command, "CompanionTui", DummyTui)

    exit_code = main(["chat"])

    assert exit_code == 0
    assert calls == [("companion", False, "win32")]


def test_companion_prompt_slash_completer_opens_for_slash_prefix():
    from prompt_toolkit.document import Document

    from src.cli_commands.companion_prompt import COMMANDS, SlashCommandCompleter

    completer = SlashCommandCompleter(COMMANDS)

    all_items = list(completer.get_completions(Document("/"), None))
    status_items = list(completer.get_completions(Document("/st"), None))
    spaced_items = list(completer.get_completions(Document("/ "), None))
    middle_items = list(completer.get_completions(Document("hello /"), None))

    assert [item.text for item in all_items] == ["/help", "/status", "/restart", "/clear", "/exit"]
    assert [item.text for item in status_items] == ["/status"]
    assert spaced_items == []
    assert middle_items == []


def test_companion_tool_event_render_hides_result_preview():
    from src.cli_commands.companion_tool_render import render_tool_event_lines

    payload = {
        "type": "tool_call_end",
        "name": "execute_console_command",
        "status": "completed",
        "duration_ms": 42,
        "result_preview": "\n".join(f"head-{index}" for index in range(1, 20)),
        "result_tail_preview": "\n".join(f"tail-{index}" for index in range(1, 10)),
        "result_chars": 4096,
        "result_tail_preview_truncated": True,
    }

    rendered = "\n".join(render_tool_event_lines(payload))

    assert "tool execute_console_command: completed (42 ms)" in rendered
    assert "4096 chars total" not in rendered
    assert "head-1" not in rendered
    assert "tail-1" not in rendered
    assert "tail-4" not in rendered
    assert "tail-9" not in rendered


def test_stream_printer_tool_event_hides_result_preview(tmp_path, capsys):
    import src.cli_commands.chat as chat_command

    printer = chat_command._StreamPrinter(
        enabled=True,
        memory_path=str(tmp_path / "memory.md"),
        messages_path=str(tmp_path / "messages.jsonl"),
    )

    printer.handle(
        {
            "type": "tool_call_end",
            "call_id": "call-1",
            "name": "read_file",
            "status": "completed",
            "duration_ms": 5,
            "result_preview": "\n".join(f"full-{index}" for index in range(1, 20)),
            "result_tail_preview": "\n".join(f"tail-{index}" for index in range(1, 10)),
            "result_chars": 2048,
            "result_tail_preview_truncated": True,
        }
    )

    output = capsys.readouterr().out
    assert "tool read_file: completed (5 ms)" in output
    assert "full-1" not in output
    assert "tail-1" not in output
    assert "tail-4" not in output
    assert "tail-9" not in output


def test_stream_printer_flushes_assistant_text_before_tool_events(tmp_path, capsys):
    import src.cli_commands.chat as chat_command

    printer = chat_command._StreamPrinter(
        enabled=True,
        memory_path=str(tmp_path / "memory.md"),
        messages_path=str(tmp_path / "messages.jsonl"),
    )

    printer.handle(
        {"type": "node_message_delta", "delta": "I will inspect first.", "text": "I will inspect first."}
    )
    printer.handle({"type": "tool_call_start", "name": "read_file"})
    printer.handle({"type": "node_message_delta", "delta": "Done.", "text": "Done."})
    printer.finish("Done.")

    output = capsys.readouterr().out
    first_note = output.index("I will inspect first.")
    tool_line = output.index("tool read_file: running")
    final_note = output.index("Done.")
    assert first_note < tool_line < final_note


def test_companion_tui_keeps_assistant_fragments_chronological():
    from types import SimpleNamespace

    from src.cli_commands.companion_tui import CompanionTui
    from src.cli_commands.companion_tui import TranscriptItem

    target = SimpleNamespace(
        config={"provider_id": "unit", "mode": "chat"},
        graph_id="companion",
        config_path="config.json",
        memory_path="memory.md",
        messages_path="messages.jsonl",
    )
    tui = CompanionTui(target, debug_terminal=False, run_turn=lambda *_args, **_kwargs: {})
    tui.state.transcript.append(TranscriptItem(role="user", text="ping"))
    tui.state.transcript.append(TranscriptItem(role="assistant", text="", status="working"))
    tui.state.active_assistant_index = 1

    tui._handle_stream(
        {"type": "node_message_delta", "delta": "I will inspect first.", "text": "I will inspect first."}
    )
    tui._handle_stream({"type": "tool_call_start", "name": "read_file"})
    tui._handle_stream({"type": "tool_call_end", "name": "read_file", "status": "completed"})
    tui._handle_stream({"type": "node_message_delta", "delta": "Done.", "text": "Done."})
    tui._finish_turn({"response": "Done."})

    rendered = [(item.role, item.text, item.status) for item in tui.state.transcript]
    assert rendered == [
        ("user", "ping", ""),
        ("assistant", "I will inspect first.", "done"),
        ("tool", "read_file: tool_call_start", ""),
        ("tool", "read_file: completed", ""),
        ("assistant", "Done.", "done"),
    ]


def test_cli_chat_plain_restart_launches_restart_and_exits(monkeypatch, tmp_path, capsys):
    import src.cli_commands.companion_terminal as companion_terminal
    from src.cli_commands.companion_restart import RestartLaunch
    from src.web_backend import runtime_paths

    config_path = tmp_path / "memories" / "companion" / "config.json"
    _write_config(
        config_path,
        {
            "graph_id": "companion",
            "type_id": "agent_node",
            "provider_id": "unit-provider",
            "mode": "chat",
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    monkeypatch.setattr("builtins.input", lambda _prompt: "/restart")
    monkeypatch.setattr(
        companion_terminal,
        "launch_restart_bat",
        lambda: RestartLaunch(script_path=str(tmp_path / "Restart.bat"), pid=1234),
    )

    exit_code = main(["chat", "--plain"])
    output = capsys.readouterr().out

    assert exit_code == 43
    assert "Started Restart.bat" in output
    assert "1234" in output


def test_cli_chat_plain_displays_companion_inbox_notice(monkeypatch, tmp_path, capsys):
    import src.companion_notice_settings as companion_notice_settings
    import src.cli_commands.chat as chat_command
    from src.companion_inbox import deliver_companion_notice
    from src.web_backend import runtime_paths

    config_path = tmp_path / "memories" / "companion" / "config.json"
    _write_config(
        config_path,
        {
            "graph_id": "companion",
            "type_id": "agent_node",
            "provider_id": "unit-provider",
            "mode": "chat",
        },
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(
        companion_notice_settings.ConfigLoader,
        "get_config",
        lambda _self: {"agentNode": {"reviewNodeRunsWithCompanion": True}},
    )
    seen_inputs = []

    class DummyAgentNode:
        def on_input(self, message, context):
            text = message["parts"][0]["text"]
            seen_inputs.append(text)
            assert context["graph_id"] == "companion"
            assert context["node_instance_id"] == "companion"
            return {
                "display": "acknowledged",
                "routes": [
                    {
                        "output_index": 0,
                        "payload": {"role": "assistant", "parts": [{"type": "text", "text": "acknowledged"}]},
                    }
                ],
            }

    monkeypatch.setattr(chat_command, "AgentNode", lambda: DummyAgentNode())
    assert deliver_companion_notice(
        {
            "type": "node_review_notice",
            "source": {"graph_id": "default", "node_id": "Agent1", "node_type_id": "agent_node"},
            "run": {
                "trace_id": "trace-1",
                "from_node": "Trigger1",
                "input_preview": "start work",
                "output_preview": "done",
                "duration_ms": 42,
                "goal_status": "complete",
            },
            "report": {
                "memory_path": str(tmp_path / "memories" / "default" / "Agent1" / "memory.md"),
                "messages_path": str(tmp_path / "memories" / "default" / "Agent1" / "messages.jsonl"),
                "runtime_events_path": str(tmp_path / "memories" / "default" / "Agent1" / "runtime_events.jsonl"),
                "report_path": str(tmp_path / "memories" / "default" / "Agent1" / "reports" / "review.md"),
            },
        },
        config_path=str(config_path),
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: "/exit")

    exit_code = main(["chat", "--plain"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "A node run was persisted. Review the full persisted run" in output
    assert "Node: default/Agent1" in output
    assert "Triggered by node: default/Trigger1" in output
    assert "Write report to:" in output
    assert "acknowledged" in output
    assert len(seen_inputs) == 1
    assert seen_inputs[0].startswith(
        "A node run was persisted. Review the full persisted run"
    )
    assert "Node: default/Agent1" in seen_inputs[0]
    assert (config_path.parent / "inbox.jsonl").read_text(encoding="utf-8") == ""
    records = [
        json.loads(line)
        for line in (config_path.parent / "messages.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [item["role"] for item in records] == ["user", "assistant"]
    assert "Triggered by node: default/Trigger1" in records[0]["parts"][0]["text"]


def test_companion_tui_edits_draft_from_key_events(tmp_path):
    from src.cli_commands.companion_console import ConsoleEvent
    from src.cli_commands.companion_tui import CompanionTui

    class Target:
        graph_id = "companion"
        config_path = "config.json"
        memory_path = "memory.md"
        messages_path = "messages.jsonl"
        config = {"provider_id": "unit-provider", "mode": "chat"}

    log_path = tmp_path / "companion-cli.log"
    tui = CompanionTui(Target(), debug_terminal=False, run_turn=lambda *args, **kwargs: {}, log_path=str(log_path))
    tui._handle_console_event(ConsoleEvent(kind="key", key="char", text="/"))
    tui._handle_console_event(ConsoleEvent(kind="key", key="char", text="help"))
    tui._handle_console_event(ConsoleEvent(kind="key", key="left"))
    tui._handle_console_event(ConsoleEvent(kind="key", key="backspace"))
    tui._handle_console_event(ConsoleEvent(kind="key", key="char", text="l"))
    tui._handle_console_event(ConsoleEvent(kind="key", key="end"))
    tui._handle_console_event(ConsoleEvent(kind="key", key="enter"))

    assert tui.state.draft == ""
    assert tui.state.transcript[-1].role == "help"
    assert "Enter      submit" in tui.state.transcript[-1].text
    assert tui.state.key_events_seen == 7
    assert tui.state.last_key == "enter"
    log_text = log_path.read_text(encoding="utf-8")
    assert "\tkey\tchar:/" in log_text
    assert "\tkey\tenter" in log_text


def test_cli_doctor_reports_invalid_mcp_server_manifest(monkeypatch, tmp_path, capsys):
    import src.cli_commands.doctor as doctor_command
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(doctor_command, "load_workspace_settings", lambda: {"mcpServers": {"bad": {"transport": "stdio"}}})
    monkeypatch.setattr(doctor_command, "default_skill_root", lambda: str(tmp_path / "missing_skills"))
    monkeypatch.setattr(doctor_command, "default_plugin_root", lambda: str(tmp_path / "missing_plugins"))

    exit_code = main(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    mcp_checks = [item for item in payload["checks"] if item["name"] == "mcp_server:bad"]

    assert exit_code == 1
    assert mcp_checks
    assert "command is required" in mcp_checks[0]["detail"]


def test_cli_doctor_reports_invalid_skill_manifest(monkeypatch, tmp_path, capsys):
    import src.cli_commands.doctor as doctor_command
    from src.capabilities.discovery_cache import invalidate_discovery_cache
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    skill_root = tmp_path / "skills"
    bad_skill = skill_root / "bad"
    bad_skill.mkdir(parents=True)
    (bad_skill / "SKILL.md").write_text("missing frontmatter\n", encoding="utf-8")
    invalidate_discovery_cache("skills", str(skill_root))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(doctor_command, "load_workspace_settings", lambda: {})
    monkeypatch.setattr(doctor_command, "default_skill_root", lambda: str(skill_root))
    monkeypatch.setattr(doctor_command, "default_plugin_root", lambda: str(tmp_path / "missing_plugins"))

    exit_code = main(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    skill_checks = [item for item in payload["checks"] if item["name"] == "skill:bad"]

    assert exit_code == 1
    assert skill_checks
    assert "missing YAML frontmatter" in skill_checks[0]["detail"]


def test_cli_doctor_reports_invalid_plugin_manifest(monkeypatch, tmp_path, capsys):
    import src.cli_commands.doctor as doctor_command
    from src.capabilities.discovery_cache import invalidate_discovery_cache
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    plugin_root = tmp_path / "plugins"
    bad_plugin = plugin_root / "bad"
    bad_plugin.mkdir(parents=True)
    (bad_plugin / "agentpark.plugin.json").write_text(
        '{"id":"bad","configSchema":[]}',
        encoding="utf-8",
    )
    invalidate_discovery_cache("plugins", str(plugin_root))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))
    monkeypatch.setattr(doctor_command, "load_workspace_settings", lambda: {})
    monkeypatch.setattr(doctor_command, "default_skill_root", lambda: str(tmp_path / "missing_skills"))
    monkeypatch.setattr(doctor_command, "default_plugin_root", lambda: str(plugin_root))

    exit_code = main(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    plugin_checks = [item for item in payload["checks"] if item["name"] == "plugin:bad"]

    assert exit_code == 1
    assert plugin_checks
    assert "configSchema must be an object" in plugin_checks[0]["detail"]


def test_packaged_fast_api_entry_dispatches_cli_subcommands(monkeypatch):
    import src.cli as cli_module
    import src.fast_api as fast_api

    calls = []

    def fake_cli_main(argv):
        calls.append(list(argv))
        return 7

    monkeypatch.setattr(cli_module, "main", fake_cli_main)

    try:
        fast_api.main(["doctor", "--json"])
    except SystemExit as exc:
        exit_code = exc.code
    else:
        raise AssertionError("fast_api.main should exit after CLI dispatch")

    assert exit_code == 7
    assert calls == [["doctor", "--json"]]
