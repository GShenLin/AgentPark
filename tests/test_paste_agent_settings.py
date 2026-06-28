import json

import pytest

from src.web_backend.paste_agent_settings import PasteAgentSettings
from src.web_backend.shared import HTTPException


def test_paste_agent_config_missing_file_is_created(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    service = PasteAgentSettings(object())

    payload = service.get_paste_agent_config()
    config_path = tmp_path / "config" / "pastagent.json"

    assert payload["config"]["agent_id"] == "pastagent"
    assert json.loads(config_path.read_text(encoding="utf-8"))["agent_id"] == "pastagent"


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
