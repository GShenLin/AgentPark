import json

import pytest

from src import workspace_settings
from src.config_loader import ConfigLoader
from src.provider_model_discovery import run_provider_model_discovery
from src.provider_model_settings import append_discovered_model_ids


@pytest.fixture
def provider_config(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "modelProvider.json"
    payload = {
        "description": "模型配置",
        "providers": {
            "demo": {
                "type": "openai",
                "apiKey": "test-key",
                "baseUrl": "https://example.test/v1",
                "model": "default-model",
                "models": ["default-model", "manual-model"],
            },
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(path))
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    return path, payload


def test_discovery_appends_missing_models_and_preserves_latest_raw_settings(monkeypatch, provider_config):
    path, payload = provider_config

    def discover(provider, *, timeout_seconds):
        # Simulate a settings edit made while the provider request was in flight.
        payload["providers"]["demo"]["models"].append("added-during-request")
        payload["providers"]["demo"]["apiKey"] = "updated-key"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return {
            "supported": True,
            "tested_at": "2026-09-17 12:00:00",
            "model_ids": ["new-model", "manual-model", "new-model"],
        }

    monkeypatch.setattr("src.provider_model_discovery.discover_provider_models", discover)
    result = run_provider_model_discovery(timeout_seconds=1)

    payload["providers"]["demo"]["models"].append("new-model")
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    assert result["model_refresh_status"] == "finished"
    assert ConfigLoader().get_provider_catalog()["demo"]["models"] == [
        "default-model", "manual-model", "added-during-request", "new-model",
    ]


@pytest.mark.parametrize("model", ["default-model", ["default-model", "manual-model"]])
def test_discovery_supports_existing_model_formats(provider_config, model):
    path, payload = provider_config
    provider = payload["providers"]["demo"]
    del provider["models"]
    provider["model"] = model
    path.write_text(json.dumps(payload), encoding="utf-8")

    append_discovered_model_ids(str(path), "demo", ["new-model", "default-model"])

    saved = json.loads(path.read_text(encoding="utf-8"))["providers"]["demo"]
    assert "models" not in saved
    assert saved["model"] == ([model] if isinstance(model, str) else model) + ["new-model"]
    assert ConfigLoader().get_provider_catalog()["demo"]["model"] == "default-model"


def test_repeated_discovery_does_not_rewrite_config(monkeypatch, provider_config):
    path, _ = provider_config
    append_discovered_model_ids(str(path), "demo", ["new-model"])

    def unexpected_write(*args, **kwargs):
        pytest.fail("Unchanged model lists must not rewrite the configuration")

    monkeypatch.setattr("src.provider_model_settings.atomic_write_text", unexpected_write)
    append_discovered_model_ids(str(path), "demo", ["new-model", "manual-model", "new-model"])


@pytest.mark.parametrize("supported", [True, False])
def test_empty_or_failed_discovery_keeps_config(monkeypatch, provider_config, supported):
    path, _ = provider_config
    original = path.read_bytes()
    monkeypatch.setattr(
        "src.provider_model_discovery.discover_provider_models",
        lambda *args, **kwargs: {
            "supported": supported,
            "tested_at": "2026-09-17 12:00:00",
            "model_ids": [],
            "reason": "" if supported else "HTTP 401",
        },
    )
    run_provider_model_discovery(timeout_seconds=1)
    assert path.read_bytes() == original


def test_config_write_failure_is_reported(monkeypatch, provider_config):
    path, _ = provider_config

    def fail_write(*args, **kwargs):
        raise OSError("configuration is read-only")

    monkeypatch.setattr("src.provider_model_settings.atomic_write_text", fail_write)
    with pytest.raises(OSError, match="read-only"):
        append_discovered_model_ids(str(path), "demo", ["new-model"])


def test_invalid_allowlist_is_not_silently_replaced(provider_config):
    path, payload = provider_config
    payload["providers"]["demo"]["models"] = "invalid"
    path.write_text(json.dumps(payload), encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(ValueError, match="must be an array"):
        append_discovered_model_ids(str(path), "demo", ["new-model"])
    assert path.read_bytes() == original
