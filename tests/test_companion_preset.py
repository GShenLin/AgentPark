import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.companion_config import (
    companion_config_signature, read_companion_config, update_companion_fields,
)
from src.config_loader import ConfigLoader
from src.web_backend.settings_api import SettingsApiDomain


@pytest.fixture
def companion(monkeypatch, tmp_path):
    from src.web_backend import profile_storage, runtime_paths
    monkeypatch.setattr(profile_storage, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path / "memories"))
    monkeypatch.setattr(ConfigLoader, "get_all_providers", lambda _: {
        "p": {"models": ["first", "second"], "supportmode": ["chat"]},
    })
    preset = tmp_path / "agent" / "Companion.json"
    preset.parent.mkdir()
    preset.write_text(json.dumps({
        "id": "Companion", "name": "Companion", "node_type_id": "agent_node",
        "fields": {"provider_id": "p", "model": "second", "reasoning_effort": "high",
                   "system_prompt": "Preset prompt", "tools": ["console_tools"],
                   "working_path": "preset-directory", "remote_enabled": True},
    }), encoding="utf-8")
    path = tmp_path / "memories" / "Companion" / "Companion" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"profile_id": "Companion", "working_path": "local-directory"}), encoding="utf-8")
    return path, preset


def test_settings_store_only_reference_and_reject_invalid_selection(companion):
    path, _ = companion
    domain = SettingsApiDomain(SimpleNamespace())
    original = path.read_text()
    for binding in [{}, {"profile_id": "missing"}, {"profile_id": 4},
                    {"profile_id": "../Companion"}, {"profile_id": "Companion", "model": "first"}]:
        with pytest.raises(HTTPException) as exc:
            domain.update_settings_section("companion", {"content": json.dumps(binding)})
        assert exc.value.status_code == 400
        assert path.read_text() == original
    result = domain.update_settings_section("companion", {
        "content": json.dumps({"profile_id": "Companion", "working_path": "new-directory"}),
    })
    assert result["data"] == {"profile_id": "Companion", "working_path": "new-directory"}
    assert json.loads(path.read_text()) == result["data"]


@pytest.mark.parametrize("change", [
    {"node_type_id": "echo_node"}, {"fields": []},
    {"fields": {"provider_id": "p"}},
    {"fields": {"provider_id": "p", "model": "missing"}},
    {"fields": {"provider_id": "unknown", "model": "first"}},
    {"fields": {"provider_id": "p", "model": "first", "graph_id": "hijack"}},
])
def test_invalid_preset_fails_explicitly(companion, change):
    path, preset = companion
    doc = json.loads(preset.read_text())
    preset.write_text(json.dumps({**doc, **change}), encoding="utf-8")
    with pytest.raises(ValueError):
        read_companion_config(str(path))


def test_next_turn_reloads_preset_without_copying_fields_to_node(companion, monkeypatch):
    from src.cli_commands import chat
    path, preset = companion
    before = path.read_text()
    target = chat.resolve_chat_target()
    assert target.config["model"] == "second"
    assert target.config["working_path"] == "local-directory"
    signature = companion_config_signature(str(path))
    doc = json.loads(preset.read_text())
    doc["fields"]["model"] = "first"
    doc["fields"]["system_prompt"] = "Updated preset prompt"
    preset.write_text(json.dumps(doc), encoding="utf-8")
    assert companion_config_signature(str(path)) != signature
    calls = []
    class Node:
        def on_input(self, message, context):
            calls.append(context)
            return {"display": "done"}
    monkeypatch.setattr(chat, "AgentNode", Node)
    chat._run_one_turn(target, "hello", print_stream=False)
    assert calls[0]["model"] == "first"
    assert calls[0]["system_prompt"] == "Updated preset prompt"
    assert calls[0]["tools"] == ["console_tools"]
    assert path.read_text() == before


def test_cli_field_updates_write_to_selected_preset(companion):
    path, preset = companion
    before = path.read_text()
    update_companion_fields(str(path), lambda fields: fields.update(reasoning_effort="medium"))
    assert json.loads(preset.read_text())["fields"]["reasoning_effort"] == "medium"
    assert path.read_text() == before


def test_unconfigured_reference_remains_readable_in_settings(companion):
    path, _ = companion
    path.write_text('{"profile_id":"deleted"}', encoding="utf-8")
    assert SettingsApiDomain(SimpleNamespace()).get_settings_section("companion")["data"] == {"profile_id": "deleted"}


def test_settings_select_preset_from_inline_config(companion):
    path, preset = companion
    preset_before = preset.read_text()
    local = {"node_id": "Companion", "graph_id": "Companion", "type_id": "agent_node",
             "working_path": "local-directory", "ui": {"grid_x": 2, "grid_y": 3}}
    inline = {**local, "provider_id": "old", "model": "old-model", "tools": ["old-tool"],
              "asr_audio_bits": 16, "system_prompt": "Old instructions"}
    path.write_text(json.dumps(inline), encoding="utf-8")
    domain = SettingsApiDomain(SimpleNamespace())
    document = domain.get_settings_section("companion")
    assert document["data"] == local
    assert json.loads(document["content"]) == local
    assert document["warnings"]
    assert json.loads(path.read_text()) == inline  # Reading never rewrites user settings.
    selected = {**json.loads(document["content"]), "profile_id": "Companion"}
    domain.update_settings_section("companion", {"content": json.dumps(selected)})
    assert json.loads(path.read_text()) == selected
    assert preset.read_text() == preset_before
    effective = read_companion_config(str(path))
    assert effective["model"] == "second"
    assert effective["tools"] == ["console_tools"]
    assert effective["working_path"] == "local-directory"
    assert not domain.get_settings_section("companion")["warnings"]
