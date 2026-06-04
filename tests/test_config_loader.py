import json

import pytest

from src.config_loader import ConfigLoader


def _reset_loader_singleton():
    ConfigLoader._instance = None


def test_get_config_returns_normalized_payload_and_supports_explicit_config_path(monkeypatch, tmp_path):
    config_path = tmp_path / "moduleProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "Gemini",
                        "apiKey": "inline-secret",
                        "supportmode": ["chat", "chat", "imagechat"],
                        "timeoutMs": "1500",
                    }
                },
                "agentNode": {"minSendDelayMs": 120},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AITOOLS_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    loader = ConfigLoader()
    payload = loader.get_config()

    assert payload["agentNode"]["minSendDelayMs"] == 120
    assert payload["providers"]["demo"]["type"] == "gemini"
    assert payload["providers"]["demo"]["supportmode"] == ["chat", "imagechat"]
    assert payload["providers"]["demo"]["timeoutMs"] == 1500
    assert payload["providers"]["demo"]["apiKey"] == "inline-secret"


def test_get_provider_config_requires_non_empty_api_key(monkeypatch, tmp_path):
    config_path = tmp_path / "moduleProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "doubao",
                        "apiKey": "   ",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AITOOLS_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    loader = ConfigLoader()

    providers = loader.get_all_providers()
    assert providers["demo"]["apiKey"] == ""

    with pytest.raises(ValueError, match="non-empty apiKey"):
        loader.get_provider_config("demo")


def test_get_provider_config_still_accepts_direct_api_key(monkeypatch, tmp_path):
    config_path = tmp_path / "moduleProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "doubao",
                        "apiKey": "inline-secret",
                        "supportmode": [],
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AITOOLS_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    payload = ConfigLoader().get_provider_config("demo")

    assert payload["apiKey"] == "inline-secret"
    assert payload["type"] == "doubao"


def test_get_config_reloads_from_disk_when_file_changes(monkeypatch, tmp_path):
    config_path = tmp_path / "moduleProvider.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "gemini",
                        "apiKey": "inline-secret",
                        "model": "model-v1",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AITOOLS_CONFIG_PATH", str(config_path))
    _reset_loader_singleton()

    loader = ConfigLoader()
    first = loader.get_provider_config("demo")
    assert first["model"] == "model-v1"

    config_path.write_text(
        json.dumps(
            {
                "providers": {
                    "demo": {
                        "type": "gemini",
                        "apiKey": "inline-secret",
                        "model": "model-v2",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    second = loader.get_provider_config("demo")
    assert second["model"] == "model-v2"
