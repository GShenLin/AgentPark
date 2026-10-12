import json
from types import SimpleNamespace

import pytest

from src.config_loader import ConfigLoader
from src.tool_context_compaction_gate import ToolContextCompactionGateMixin
from src.web_backend.settings_api import SettingsApiDomain


@pytest.mark.parametrize("responses_api", [False, True])
@pytest.mark.parametrize("enabled", [None, False, True])
def test_provider_compaction_default_survives_save_load_and_runtime(
    monkeypatch, tmp_path, responses_api, enabled
):
    from src import workspace_settings

    monkeypatch.delenv("AGENTPARK_CONFIG_PATH", raising=False)
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    provider = {
        "type": "openai",
        "apiKey": "test-key",
        "responsesApi": responses_api,
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
    }
    if enabled is not None:
        provider["toolContextCompactionEnabled"] = enabled
    result = SettingsApiDomain(SimpleNamespace()).update_settings_section(
        "model-provider", {"content": json.dumps({"providers": {"demo": provider}})}
    )
    assert result["ok"] is True
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(tmp_path / "config" / "modelProvider.json"))
    loaded = ConfigLoader().get_all_providers()["demo"]
    agent = SimpleNamespace(config=loaded)
    assert ToolContextCompactionGateMixin._tool_context_compaction_enabled(agent) is (
        False if enabled is None else enabled
    )
