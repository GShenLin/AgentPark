import json
from types import SimpleNamespace

import pytest

from src.provider_limit_jobs import ProviderLimitJobStore
from src.provider_limit_view import read_current_provider_limits
from src.web_backend.settings_api import SettingsApiDomain


@pytest.fixture
def documents(monkeypatch, tmp_path):
    config_path = tmp_path / "modelProvider.json"
    limits_path = tmp_path / "ProviderLimit.json"
    monkeypatch.setenv("AGENTPARK_CONFIG_PATH", str(config_path))
    return config_path, limits_path


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def provider(model="demo-model"):
    return {"type": "openai", "apiKey": "unresolved-key-name", "model": model}


def test_limits_follow_catalog_preserving_evidence_without_resolving_credentials(documents, monkeypatch):
    config_path, limits_path = documents
    write_json(config_path, {"providers": {"new": provider(["first", "second"]), "kept": provider()}})
    evidence = {
        "provider_id": "kept", "accessible": True, "tested_at": "2026-10-19",
        "features": {"access": {"supported": True}},
        "channels": {"responses": {"accessible": True}},
        "available_model_ids": ["discovered"], "manual_model_ids": ["manual"],
    }
    write_json(limits_path, {"providers": {"deleted": {"accessible": True}, "kept": evidence}})
    original = limits_path.read_bytes()

    def reject_credentials(*args, **kwargs):
        pytest.fail("Reading provider test settings must not resolve credentials")

    monkeypatch.setattr("src.config_loader.resolve_provider_credential_references", reject_credentials)
    result = read_current_provider_limits()
    assert list(result["providers"]) == ["new", "kept"]
    new = result["providers"]["new"]
    assert new["model"] == "first"
    assert new["available_model_ids"] == ["first", "second"]
    assert new["tested_at"] == ""
    assert "accessible" not in new  # Untested is distinct from unavailable.
    assert "apiKey" not in new
    assert all(result["providers"]["kept"][key] == value for key, value in evidence.items())
    assert limits_path.read_bytes() == original


def test_settings_save_and_job_poll_use_current_membership(documents):
    config_path, limits_path = documents
    write_json(config_path, {"providers": {"old": provider()}})
    write_json(limits_path, {"providers": {"old": {"accessible": True}}})
    jobs = ProviderLimitJobStore()
    jobs._jobs["test"] = {"job_id": "test", "status": "running"}
    domain = SettingsApiDomain(SimpleNamespace(provider_limit_jobs=jobs))
    assert list(domain.get_provider_limits()["providers"]) == ["old"]

    domain.update_settings_section("model-provider", {
        "content": json.dumps({"providers": {"renamed": provider()}}),
    })
    assert list(domain.get_provider_limits()["providers"]) == ["renamed"]
    for result in (
        domain.get_provider_limit_test_job("test"),
        domain.start_provider_limit_tests(),
        domain.start_provider_model_discovery(),
    ):
        assert list(result["result"]["providers"]) == ["renamed"]
        assert "accessible" not in result["result"]["providers"]["renamed"]

    # Direct file edits are visible too; no server restart or probe is required.
    write_json(config_path, {"providers": {}})
    assert domain.get_provider_limits()["providers"] == {}
    assert jobs.read_result()["providers"] == {}


def test_missing_snapshot_still_lists_configured_providers(documents):
    config_path, limits_path = documents
    write_json(config_path, {"providers": {"new": provider()}})
    result = read_current_provider_limits()
    assert list(result["providers"]) == ["new"]
    assert result["providers"]["new"]["features"] == {}
    assert not limits_path.exists()


@pytest.mark.parametrize("snapshots", [[], {"demo": None}])
def test_invalid_snapshot_is_not_masked_as_untested(documents, snapshots):
    config_path, limits_path = documents
    write_json(config_path, {"providers": {"demo": provider()}})
    write_json(limits_path, {"providers": snapshots})
    with pytest.raises(ValueError, match="must be an object"):
        read_current_provider_limits()
