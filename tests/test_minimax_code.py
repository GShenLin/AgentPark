from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest
import yaml

from src.harness.adapters.minimax_config import configure_home, model_selection, permission_selection
from src.harness.adapters.minimax_events import MiniMaxEvents
from src.harness.events import HarnessEvents


def selection(value):
    return {"configOptions": [{"id": "model", "type": "select", "options": [{"value": value}]}]}


def test_permissions_require_exact_advertised_native_control():
    control = {"configOptions": [{"id": "permissionMode", "type": "select",
                                 "options": [{"value": "auto"}, {"value": "bypassPermissions"}]}]}
    assert permission_selection(control, "bypassPermissions") == "bypassPermissions"
    with pytest.raises(ValueError, match="requested permission"):
        permission_selection(control, "invented-mode")
    with pytest.raises(ValueError, match="permissionMode"):
        permission_selection(selection("unrelated"), "auto")
    control["configOptions"][0]["options"].append({"value": "auto"})
    with pytest.raises(ValueError, match="requested permission"):
        permission_selection(control, "auto")


def test_model_selection_uses_advertised_bound_provider_and_rejects_ambiguity():
    value = "m:custom_provider%3Aagentpark:org%2Fmodel:v:thinking"
    assert model_selection(selection(value), "org/model") == value
    for invalid in ["m:minimax:org%2Fmodel:v:thinking", "m:custom_provider%3Aagentpark:other:u", "invalid"]:
        with pytest.raises(ValueError):
            model_selection(selection(invalid), "org/model")
    control = selection(value)
    control["configOptions"][0]["options"].append({"value": value})
    with pytest.raises(ValueError, match="exactly one"):
        model_selection(control, "org/model")


def test_configuration_refreshes_lease_and_keeps_old_model_descriptors():
    from tempfile import TemporaryDirectory
    from pathlib import Path
    with TemporaryDirectory(prefix="mc-conf-") as directory:
        request = SimpleNamespace(state_dir=Path(directory), reasoning_effort="high",
            binding=SimpleNamespace(model_id="first", request_config=lambda: {
                "type": "openai", "model": "first", "modelContextWindowTokens": 64000, "maxTokens": 8192,
                "apiKey": "upstream-secret"}))
        lease = SimpleNamespace(base_url="http://localhost/v1/lease-one", token="lease-one")
        env = {}
        home = configure_home(request, lease, env)
        config = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
        assert config["custom_provider"]["agentpark"]["models"]["first"]["limit"] == {"context": 64000, "output": 8192}
        assert config["defaultLightModel"] == "custom_provider:agentpark/first"
        assert config["sessionTitle"] == {"enabled": False}
        (home / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
        request.binding.model_id = "second"
        lease.token = "lease-two"
        configure_home(request, lease, env)
        config = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))
        assert set(config["custom_provider"]["agentpark"]["models"]) == {"first", "second"}
        assert config["custom_provider"]["agentpark"]["options"]["apiKey"] == "lease-two"
        assert "upstream-secret" not in json.dumps(config)
        assert env["MINIMAX_DATA_DIR"] == str(home)
        request.binding.request_config = lambda: {"type": "openai", "maxTokens": False}
        with pytest.raises(ValueError, match="positive integer"):
            configure_home(request, lease, env)


@pytest.mark.skipif(os.name != "nt", reason="Published Windows SQLite path constraint")
def test_windows_long_backup_path_fails_before_creating_native_state(tmp_path):
    request = SimpleNamespace(state_dir=tmp_path / ("long-node-name-" * 12))
    with pytest.raises(ValueError, match="SQLite backup exceeds Windows MAX_PATH"):
        configure_home(request, None, {})
    assert not request.state_dir.exists()


def parser_fixture():
    emitted = []
    parser = MiniMaxEvents(HarnessEvents("minimax_code", "provider", emitted.append))
    parser.bind("s")
    return parser, emitted


def send(parser, kind, **fields):
    parser.handle({"sessionId": "s", "update": {"sessionUpdate": kind, **fields}})


def test_text_reasoning_and_partial_tools_project_once():
    parser, emitted = parser_fixture()
    send(parser, "agent_thought_chunk", content={"type": "text", "text": "thinking"})
    send(parser, "tool_call", toolCallId="t", title="read", status="pending")
    send(parser, "tool_call_update", toolCallId="t", status="in_progress", rawInput={"path": "中文.txt"})
    send(parser, "tool_call_update", toolCallId="t", status="completed", rawOutput="contents")
    send(parser, "agent_message_chunk", content={"type": "text", "text": "done"})
    result = parser.finish({"stopReason": "end_turn"})
    assert result.text == "done"
    assert [e["type"] for e in emitted].count("tool_call_start") == 1
    assert [e["type"] for e in emitted].count("tool_call_end") == 1
    tool = result.metadata["response_metadata"]["runtime_tool_calls"][0]
    assert tool["arguments"] == {"path": "中文.txt"}
    assert tool["result_preview"] == "contents"


def test_completed_initial_tool_and_failed_tool_keep_outcomes():
    parser, emitted = parser_fixture()
    send(parser, "tool_call", toolCallId="t", title="read", status="failed", rawOutput={"error": "missing"})
    assert emitted[-1]["type"] == "tool_call_end"
    assert emitted[-1]["status"] == "failed"
    with pytest.raises(ValueError, match="active call"):
        send(parser, "tool_call_update", toolCallId="t", status="completed")


@pytest.mark.parametrize("kind,fields", [
    ("tool_call_update", {"toolCallId": "missing", "status": "completed"}),
    ("agent_message_chunk", {"content": {"type": "image"}}),
    ("new-unknown-update", {}),
])
def test_invalid_events_fail_explicitly(kind, fields):
    parser, _ = parser_fixture()
    with pytest.raises(ValueError):
        send(parser, kind, **fields)


def test_failed_cancelled_empty_and_unfinished_turns_are_not_success():
    parser, _ = parser_fixture()
    for reason in ("cancelled", "max_tokens", "error", None):
        with pytest.raises(RuntimeError, match="turn ended"):
            parser.finish({"stopReason": reason})
    with pytest.raises(RuntimeError, match="without assistant"):
        parser.finish({"stopReason": "end_turn"})
    send(parser, "tool_call", toolCallId="t", title="read", status="pending")
    with pytest.raises(ValueError, match="unfinished"):
        parser.finish({"stopReason": "end_turn"})
    with pytest.raises(ValueError, match="different session"):
        parser.handle({"sessionId": "other", "update": {}})
