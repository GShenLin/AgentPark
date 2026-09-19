import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.config_loader import ConfigLoader
from src.web_backend.settings_api import SettingsApiDomain


@pytest.mark.parametrize("binding", [
    {"provider_id": "p"}, {"model": "m"}, {"provider_id": "p", "model": "wrong"},
    {"provider_id": "p", "model": 42}, {"provider_id": "unknown", "model": "m"},
])
def test_invalid_companion_binding_does_not_overwrite_settings(monkeypatch, tmp_path, binding):
    from src.web_backend import runtime_paths
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path))
    monkeypatch.setattr(ConfigLoader, "get_all_providers", lambda self: {"p": {"models": ["m"]}})
    path = tmp_path / "Companion" / "Companion" / "config.json"
    path.parent.mkdir(parents=True)
    original = '{"provider_id":"p","model":"m"}'
    path.write_text(original, encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        SettingsApiDomain(SimpleNamespace()).update_settings_section("companion", {"content": json.dumps(binding)})
    assert exc.value.status_code == 400
    assert path.read_text(encoding="utf-8") == original


def test_unconfigured_model_can_be_opened_for_editing(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path))
    path = tmp_path / "Companion" / "Companion" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"provider_id":"p"}', encoding="utf-8")
    assert SettingsApiDomain(SimpleNamespace()).get_settings_section("companion")["data"] == {"provider_id": "p"}
