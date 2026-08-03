import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.web_backend.provider_auth_api import ProviderAuthApiDomain


def test_provider_auth_api_lists_names_and_adds_alias_without_returning_secrets(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    domain = ProviderAuthApiDomain(SimpleNamespace())

    assert domain.get_api_key_aliases() == {"names": []}

    result = domain.add_api_key_alias({"name": "Work", "apiKey": "secret-value"})

    assert result == {"names": ["Work"], "selected": "Work"}
    assert "secret-value" not in repr(result)
    store_path = tmp_path / ".auth" / "api-keys" / "aliases.json"
    assert json.loads(store_path.read_text(encoding="utf-8")) == {"Work": "secret-value"}
    assert domain.get_api_key_aliases() == {"names": ["Work"]}


def test_provider_auth_api_rejects_duplicate_alias(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    domain = ProviderAuthApiDomain(SimpleNamespace())
    domain.add_api_key_alias({"name": "Work", "apiKey": "secret-value"})

    with pytest.raises(HTTPException) as exc:
        domain.add_api_key_alias({"name": "Work", "apiKey": "other-secret"})

    assert exc.value.status_code == 409
    assert "already exists" in str(exc.value.detail)


def test_provider_auth_api_rejects_empty_alias_fields(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    domain = ProviderAuthApiDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        domain.add_api_key_alias({"name": "", "apiKey": ""})

    assert exc.value.status_code == 400
    assert "name is required" in str(exc.value.detail)
