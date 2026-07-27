from __future__ import annotations

import json
import os
from types import SimpleNamespace

from nodes.claude_node import Node
from nodes.claude_node.runtime.session_state import SESSION_STATE_FILENAME
from nodes.claude_node.runtime.session_state import session_runtime_key


def test_claude_node_exposes_provider_and_native_permission_contract(monkeypatch):
    captured = {}

    def fake_provider_options(supported_modes, *, include_private=True):
        captured["supported_modes"] = set(supported_modes)
        captured["include_private"] = include_private
        return [{"value": "provider-a", "label": "provider-a"}]

    monkeypatch.setattr(
        "nodes.claude_node.build_provider_options_for_support_modes",
        fake_provider_options,
    )
    node = Node()
    schema = node.get_config_schema({"_include_private_providers": False})
    defaults = node.get_config_defaults({})

    assert node.name == "Claude"
    assert schema["provider_id"]["options"][0]["value"] == "provider-a"
    assert captured == {
        "supported_modes": {"chat", "imagechat"},
        "include_private": False,
    }
    assert [item["value"] for item in schema["permission_mode"]["options"]] == [
        "plan",
        "dontAsk",
        "acceptEdits",
        "auto",
        "bypassPermissions",
    ]
    assert defaults["claude_command"] == "claude"
    assert defaults["permission_mode"] == "acceptEdits"


def test_claude_node_uses_native_session_state_and_live_bridge(tmp_path, monkeypatch):
    node_dir = tmp_path / "Claude"
    node_dir.mkdir()
    config_path = node_dir / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "node_id": "Claude",
                "type_id": "claude_node",
                "provider_id": "provider-a",
                "working_path": str(tmp_path),
                "permission_mode": "bypassPermissions",
            }
        ),
        encoding="utf-8",
    )
    captured = {}
    stream_events = []

    class FakeManager:
        def run_turn(self, spec, text, **kwargs):
            captured["spec"] = spec
            captured["text"] = text
            captured["gateway_observer"] = kwargs["gateway_observer"]
            kwargs["gateway_observer"](
                {
                    "request_index": 1,
                    "provider_protocol": "openai_chat",
                }
            )
            return "done"

    monkeypatch.setattr(
        "nodes.claude_node.ConfigLoader",
        lambda: SimpleNamespace(
            get_provider_config=lambda _provider_id: {
                "model": "test-model",
                "supportmode": ["chat"],
            }
        ),
    )
    monkeypatch.setattr(
        "nodes.claude_node.ClaudeSessionManager.instance",
        lambda: FakeManager(),
    )
    context = {
        "node_config_path": str(config_path),
        "memory_path": str(node_dir / "memory.md"),
        "messages_path": str(node_dir / "messages.jsonl"),
        "graph_id": "default",
        "node_instance_id": "Claude",
        "stream_callback": stream_events.append,
    }

    result = Node().on_input("Start this session", context)

    state_path = os.path.join(str(node_dir), SESSION_STATE_FILENAME)
    assert captured["spec"].state_path == state_path
    assert captured["spec"].session_key == session_runtime_key("default", "Claude", state_path)
    assert captured["spec"].permission_mode == "bypassPermissions"
    assert captured["text"] == "Start this session"
    assert result["display"] == "done"
    assert [event["type"] for event in stream_events] == [
        "runtime_notice",
        "node_message_delta",
        "node_message_done",
    ]
    assert result["memory_sidecars"][0]["parts"][0]["data"]["response_metadata"][
        "provider_gateway_requests"
    ][0]["provider_protocol"] == "openai_chat"

    context["access_role"] = "nondeveloper"
    Node().on_input("Restricted session", context)
    assert captured["spec"].permission_mode == "plan"
