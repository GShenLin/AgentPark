from dataclasses import asdict
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.config_loader import ConfigLoader
from src.long_term_memory.settings import MemorySettings
from src.conversation_context.settings import ConversationSettings
from src.web_backend.settings_api import SettingsApiDomain


@pytest.fixture
def settings_workspace(tmp_path, monkeypatch):
    from src import workspace_settings
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "config.json"
    path.write_text(json.dumps({"agentNode": {"historyMessageLimit": 6}, "customSetting": "preserve"}), encoding="utf-8")
    provider_path = config_dir / "modelProvider.json"
    provider_path.write_text('{"providers":{}}', encoding="utf-8")
    monkeypatch.setenv(ConfigLoader.CONFIG_PATH_ENV, str(provider_path))
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    return SettingsApiDomain(SimpleNamespace()), path


def test_settings_exposes_authoritative_defaults_without_writing_config(settings_workspace):
    api, path = settings_workspace
    before = path.read_bytes()
    document = api.get_settings_section("defaults")
    assert document["long_term_memory_defaults"] == asdict(MemorySettings())
    assert document["conversation_context_defaults"] == asdict(ConversationSettings())
    assert "longTermMemory" not in document["data"]
    assert path.read_bytes() == before


def test_conversation_context_settings_roundtrip(settings_workspace):
    api, path = settings_workspace
    payload = api.get_settings_section("defaults")["data"]
    cfg = ConversationSettings(input_tokens=12000, retain_tokens=3000, summary_tokens=1000, provider="compact")
    payload["conversationContext"] = asdict(cfg)
    response = api.update_settings_section("defaults", {"content": json.dumps(payload)})
    assert not response["restart_required"]
    assert ConversationSettings.from_config(ConfigLoader().get_workspace_config()) == cfg
    assert json.loads(path.read_text(encoding="utf-8"))["conversationContext"] == asdict(cfg)


@pytest.mark.parametrize("raw", [{"input_tokens": 100}, {"summary_tokens": True}, {"provider": []},
                                  {"retain_tokens": 23999}, {"unknown": 1}, []])
def test_invalid_conversation_settings_do_not_write(settings_workspace, raw):
    api, path = settings_workspace
    before = path.read_bytes()
    with pytest.raises(HTTPException) as error:
        api.update_settings_section("defaults", {"content": json.dumps({"conversationContext": raw})})
    assert error.value.status_code == 400
    assert path.read_bytes() == before


def test_settings_save_roundtrip_is_read_by_runtime_config_loader(settings_workspace):
    api, path = settings_workspace
    payload = api.get_settings_section("defaults")["data"]
    settings = MemorySettings(enabled=False, extract_provider="extract-model", consolidation_provider="merge-model",
                              min_idle_seconds=0, max_age_days=20, max_unused_days=40, max_extractions=3,
                              max_selected=16, input_bytes=120000, consolidation_bytes=200000,
                              lease_seconds=90, retry_seconds=600)
    payload["longTermMemory"] = asdict(settings)
    response = api.update_settings_section("defaults", {"content": json.dumps(payload)})
    assert response["ok"]
    assert not response["restart_required"]
    assert response["long_term_memory_defaults"]["min_idle_seconds"] == 3600
    assert api.get_settings_section("defaults")["data"]["longTermMemory"] == asdict(settings)
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["agentNode"]["historyMessageLimit"] == 6
    assert persisted["customSetting"] == "preserve"
    assert MemorySettings.from_config(ConfigLoader().get_workspace_config()) == settings


@pytest.mark.parametrize("settings", [
    {"min_idle_seconds": -1}, {"min_idle_seconds": 0.5}, {"max_extractions": 0},
    {"enabled": "false"}, {"lease_seconds": True}, {"retry_seconds": None},
    {"extract_provider": []}, {"max_selected": "64"}, {"unknown_option": 1}, [],
])
def test_invalid_memory_settings_rejected_without_writing(settings_workspace, settings):
    api, path = settings_workspace
    before = path.read_bytes()
    with pytest.raises(HTTPException) as error:
        api.update_settings_section("defaults", {"content": json.dumps({"longTermMemory": settings})})
    assert error.value.status_code == 400
    assert "longTermMemory" in str(error.value.detail)
    assert path.read_bytes() == before
