import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.web_backend.settings_api import SettingsApiDomain


def test_settings_api_reads_and_writes_module_provider(monkeypatch, tmp_path):
    from src import workspace_settings

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    provider_path = config_dir / "moduleProvider.json"
    provider_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "openai",
                        "apiKey": "test-key",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("AITOOLS_CONFIG_PATH", raising=False)
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    domain = SettingsApiDomain(SimpleNamespace())

    loaded = domain.get_settings_section("module-provider")
    assert loaded["path"] == str(provider_path)
    assert loaded["data"]["providers"]["demo"]["type"] == "openai"

    result = domain.update_settings_section(
        "module-provider",
        {
            "content": json.dumps(
                {
                    "providers": {
                        "demo": {
                            "type": "gemini",
                            "apiKey": "test-key",
                        }
                    }
                },
                ensure_ascii=False,
            )
        },
    )

    assert result["ok"] is True
    saved = json.loads(provider_path.read_text(encoding="utf-8"))
    assert saved["providers"]["demo"]["type"] == "gemini"


def test_settings_api_rejects_module_provider_without_providers(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.delenv("AITOOLS_CONFIG_PATH", raising=False)
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    domain = SettingsApiDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        domain.update_settings_section("module-provider", {"content": "{}"})

    assert exc.value.status_code == 400
    assert "providers" in str(exc.value.detail)


def test_settings_api_rejects_invalid_defaults_section(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    domain = SettingsApiDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        domain.update_settings_section("defaults", {"content": json.dumps({"server": "127.0.0.1"})})

    assert exc.value.status_code == 400
    assert "server" in str(exc.value.detail)


def test_settings_api_rejects_non_boolean_companion_error_notice_switch(monkeypatch, tmp_path):
    from src import workspace_settings

    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))

    domain = SettingsApiDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        domain.update_settings_section(
            "defaults",
            {"content": json.dumps({"agentNode": {"notifyCompanionOnError": "yes"}})},
        )

    assert exc.value.status_code == 400
    assert "notifyCompanionOnError" in str(exc.value.detail)


def test_settings_api_reads_and_writes_companion_config(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    graphs_dir = tmp_path / "memories"
    companion_dir = graphs_dir / "companion"
    companion_dir.mkdir(parents=True)
    companion_path = companion_dir / "config.json"
    companion_path.write_text(
        json.dumps(
            {
                "node_id": "companion",
                "type_id": "agent_node",
                "graph_id": "companion",
                "provider_id": "demo",
                "tools": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(graphs_dir))

    domain = SettingsApiDomain(SimpleNamespace())

    loaded = domain.get_settings_section("companion")
    assert loaded["path"] == str(companion_path)
    assert loaded["data"]["provider_id"] == "demo"

    result = domain.update_settings_section(
        "companion",
        {
            "content": json.dumps(
                {
                    "node_id": "companion",
                    "type_id": "agent_node",
                    "graph_id": "companion",
                    "provider_id": "next",
                    "tools": ["file_read_tools"],
                },
                ensure_ascii=False,
            )
        },
    )

    assert result["ok"] is True
    saved = json.loads(companion_path.read_text(encoding="utf-8"))
    assert saved["provider_id"] == "next"
    assert saved["tools"] == ["file_read_tools"]


def test_settings_api_rejects_invalid_companion_config(monkeypatch, tmp_path):
    from src.web_backend import runtime_paths

    monkeypatch.setattr(runtime_paths, "_get_graphs_dir", lambda: str(tmp_path))

    domain = SettingsApiDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        domain.update_settings_section("companion", {"content": json.dumps({"type_id": "echo_node"})})

    assert exc.value.status_code == 400
    assert "agent_node" in str(exc.value.detail)
