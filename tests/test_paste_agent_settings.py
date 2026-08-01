import json
from pathlib import Path

import pytest

from src.web_backend.paste_agent_settings import PasteAgentSettings
from src.web_backend.shared import HTTPException


def test_repository_default_paste_agent_profile_matches_config_reference():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "config" / "pastagent.json").read_text(encoding="utf-8"))
    profile = json.loads((root / "agent" / "PasteAgent.json").read_text(encoding="utf-8"))

    assert config == {"profile_id": "PasteAgent"}
    assert profile["id"] == "PasteAgent"
    assert profile["node_type_id"] == "agent_node"
    assert profile["node_name"] == "PasteAgent"
    assert isinstance(profile["fields"], dict)
    assert str(profile["fields"].get("provider_id") or "").strip()
    assert isinstance(profile["event_rules"], dict)


def test_paste_agent_config_missing_file_is_created(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    service = PasteAgentSettings(object())

    payload = service.get_paste_agent_config()
    config_path = tmp_path / "config" / "pastagent.json"

    assert payload["config"] == {"profile_id": "PasteAgent"}
    assert json.loads(config_path.read_text(encoding="utf-8")) == {"profile_id": "PasteAgent"}


def test_legacy_paste_agent_fields_are_replaced_by_default_profile_reference(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    config_path = tmp_path / "config" / "pastagent.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps({"agent_id": "pastagent", "provider_id": "legacy-provider"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    service = PasteAgentSettings(object())

    assert service.get_paste_agent_config()["config"] == {"profile_id": "PasteAgent"}
    assert json.loads(config_path.read_text(encoding="utf-8")) == {"profile_id": "PasteAgent"}


def test_paste_agent_config_corrupt_json_is_not_replaced(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    config_path = tmp_path / "config" / "pastagent.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("{bad", encoding="utf-8")
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    service = PasteAgentSettings(object())

    with pytest.raises(HTTPException) as exc:
        service.get_paste_agent_config()

    assert exc.value.status_code == 500
    assert "invalid JSON" in str(exc.value.detail)
    assert config_path.read_text(encoding="utf-8") == "{bad"


def test_paste_agent_config_non_object_json_is_not_replaced(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    config_path = tmp_path / "config" / "pastagent.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    service = PasteAgentSettings(object())

    with pytest.raises(HTTPException) as exc:
        service.get_paste_agent_config()

    assert exc.value.status_code == 500
    assert "JSON object" in str(exc.value.detail)
    assert config_path.read_text(encoding="utf-8") == "[]"


def test_paste_agent_profile_can_be_selected(monkeypatch, tmp_path):
    from src.web_backend import paste_agent_settings, runtime_paths

    profile_dir = tmp_path / "agent"
    profile_dir.mkdir()
    (profile_dir / "Researcher.json").write_text(
        json.dumps(
            {
                "id": "Researcher",
                "name": "Researcher",
                "node_type_id": "agent_node",
                "fields": {},
                "event_rules": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(paste_agent_settings, "profile_category_dir", lambda _dirname: str(profile_dir))
    service = PasteAgentSettings(object())

    payload = service.update_paste_agent_config({"profile_id": "Researcher"})

    assert payload["config"] == {"profile_id": "Researcher"}
    assert json.loads((tmp_path / "config" / "pastagent.json").read_text(encoding="utf-8")) == {
        "profile_id": "Researcher"
    }


def test_paste_agent_profile_selection_rejects_missing_profile(monkeypatch, tmp_path):
    from src.web_backend import paste_agent_settings, runtime_paths

    profile_dir = tmp_path / "agent"
    profile_dir.mkdir()
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(paste_agent_settings, "profile_category_dir", lambda _dirname: str(profile_dir))
    service = PasteAgentSettings(object())

    with pytest.raises(HTTPException) as exc:
        service.update_paste_agent_config({"profile_id": "Missing"})

    assert exc.value.status_code == 400
    assert exc.value.detail == "agent profile not found: Missing"
