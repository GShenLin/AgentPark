import json
import os
from types import SimpleNamespace

from nodes.codex_node import Node
from src.codex_runtime.thread_state import THREAD_STATE_FILENAME
from src.codex_runtime.thread_state import session_runtime_key


def test_codex_node_exposes_provider_dropdown_and_runtime_configuration(monkeypatch):
    captured = {}

    def fake_provider_options(supported_modes, *, include_private=True):
        captured["supported_modes"] = set(supported_modes)
        captured["include_private"] = include_private
        return [
            {"value": "provider-a", "label": "provider-a"},
            {"value": "provider-b", "label": "provider-b"},
        ]

    monkeypatch.setattr(
        "nodes.codex_node.build_provider_options_for_support_modes",
        fake_provider_options,
    )
    node = Node()
    schema = node.get_config_schema({"_include_private_providers": False})
    defaults = node.get_config_defaults({})

    assert node.name == "Codex"
    assert schema["provider_id"]["type"] == "select"
    assert schema["provider_id"]["options"] == [
        {"value": "provider-a", "label": "provider-a"},
        {"value": "provider-b", "label": "provider-b"},
    ]
    assert captured == {
        "supported_modes": {"chat", "imagechat"},
        "include_private": False,
    }
    assert schema["codex_command"]["type"] == "text"
    assert [item["value"] for item in schema["sandbox"]["options"]] == [
        "read-only",
        "workspace-write",
        "danger-full-access",
    ]
    assert defaults["codex_command"] == "codex"
    assert "tools" not in schema
    assert "skills" not in schema


def test_codex_node_on_input_uses_node_thread_pointer(tmp_path, monkeypatch):
    node_dir = tmp_path / "Codex"
    node_dir.mkdir()
    config_path = node_dir / "config.json"
    config_path.write_text(
        json.dumps({
            "node_id": "Codex",
            "type_id": "codex_node",
            "provider_id": "provider-a",
            "working_path": str(tmp_path),
        }),
        encoding="utf-8",
    )
    captured = {}

    class FakeManager:
        def run_turn(self, spec, text, **_kwargs):
            captured["spec"] = spec
            captured["text"] = text
            return "done"

    monkeypatch.setattr(
        "nodes.codex_node.ConfigLoader",
        lambda: SimpleNamespace(get_provider_config=lambda _provider_id: {
            "model": "test-model",
            "type": "custom",
        }),
    )
    monkeypatch.setattr(
        "nodes.codex_node.CodexSessionManager.instance",
        lambda: FakeManager(),
    )
    context = {
        "node_config_path": str(config_path),
        "memory_path": str(node_dir / "memory.md"),
        "messages_path": str(node_dir / "messages.jsonl"),
        "graph_id": "default",
        "node_instance_id": "Codex",
    }

    result = Node().on_input("Start this session", context)

    state_path = os.path.join(str(node_dir), THREAD_STATE_FILENAME)
    assert context["memory_path"] == str(node_dir / "memory.md")
    assert context["messages_path"] == str(node_dir / "messages.jsonl")
    assert captured["spec"].state_path == state_path
    assert captured["spec"].session_key == session_runtime_key("default", "Codex", state_path)
    assert captured["text"] == "Start this session"
    assert result["display"] == "done"
