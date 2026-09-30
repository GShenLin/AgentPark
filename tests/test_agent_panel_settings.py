import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src import workspace_settings
from src.agent_panel_settings import read_agent_panel_settings
from src.web_backend.settings_api import SettingsApiDomain


@pytest.fixture
def settings_domain(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENTPARK_CONFIG_PATH", raising=False)
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    return SettingsApiDomain(SimpleNamespace())


def test_agent_panel_settings_persist_and_reset(settings_domain):
    assert read_agent_panel_settings() == {"width": 1040, "height": 820}
    settings_domain.update_settings_section(
        "defaults", {"content": json.dumps({"agentPanel": {"width": 1280, "height": 960}})}
    )
    assert read_agent_panel_settings() == {"width": 1280, "height": 960}
    assert settings_domain.get_settings_section("defaults")["data"]["agentPanel"] == {
        "width": 1280, "height": 960,
    }
    settings_domain.update_settings_section(
        "defaults", {"content": json.dumps({"agentPanel": {"width": 360}})}
    )
    assert read_agent_panel_settings() == {"width": 360, "height": 820}


@pytest.mark.parametrize("value", [
    [], "large", {"width": 359}, {"height": 319}, {"width": 7681},
    {"height": 7681}, {"width": True}, {"width": "1040"},
    {"height": 820.5}, {"height": None},
])
def test_invalid_agent_panel_settings_do_not_overwrite_saved_settings(settings_domain, value):
    settings_domain.update_settings_section(
        "defaults", {"content": json.dumps({"agentPanel": {"width": 1200}})}
    )
    with pytest.raises(HTTPException) as exc:
        settings_domain.update_settings_section("defaults", {"content": json.dumps({"agentPanel": value})})
    assert exc.value.status_code == 400
    assert "agentPanel" in exc.value.detail
    assert read_agent_panel_settings() == {"width": 1200, "height": 820}
