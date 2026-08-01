import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.runtime_policy.settings_store import RuntimePolicySettingsStore
from src.web_backend.runtime_policy_settings_api import RuntimePolicySettingsApiDomain


PROJECT_ROOT = Path(__file__).parents[1]


def _copy_runtime_policy_config(target_root: Path) -> None:
    target_config = target_root / "config"
    target_config.mkdir()
    shutil.copy2(PROJECT_ROOT / "config" / "runtimePolicies.json", target_config)
    shutil.copytree(
        PROJECT_ROOT / "config" / "runtime_policies",
        target_config / "runtime_policies",
    )


def test_runtime_policy_settings_store_switches_default_and_updates_policy(tmp_path):
    _copy_runtime_policy_config(tmp_path)
    store = RuntimePolicySettingsStore(str(tmp_path))

    loaded = store.load()
    assert loaded["default_policy_id"] == "coding-default"
    assert {item["policy_id"] for item in loaded["policies"]} == {
        "architecture-design",
        "code-reading",
        "code-review",
        "coding-default",
        "coding-diagnostic",
        "coding-fast",
        "cross-module-implementation",
        "documentation-maintenance",
        "incident-diagnosis",
        "localized-implementation",
        "protocol-integration",
        "refactoring-planning",
        "test-engineering",
    }

    switched = store.update_default("coding-fast")
    assert switched["default_policy_id"] == "coding-fast"
    catalog = json.loads(
        (tmp_path / "config" / "runtimePolicies.json").read_text(encoding="utf-8")
    )
    assert catalog["default_policy_id"] == "coding-fast"

    fast = next(item for item in switched["policies"] if item["policy_id"] == "coding-fast")
    next_config = dict(fast["config"])
    next_config["description"] = "Focused local implementation."
    updated = store.update_policy("coding-fast", next_config)

    saved = next(item for item in updated["policies"] if item["policy_id"] == "coding-fast")
    assert saved["config"]["description"] == "Focused local implementation."


def test_runtime_policy_settings_store_rejects_policy_id_mismatch_without_writing(tmp_path):
    _copy_runtime_policy_config(tmp_path)
    store = RuntimePolicySettingsStore(str(tmp_path))
    loaded = store.load()
    fast = next(item for item in loaded["policies"] if item["policy_id"] == "coding-fast")
    next_config = dict(fast["config"])
    next_config["policy_id"] = "coding-default"
    policy_path = tmp_path / fast["path"]
    baseline = policy_path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="must equal its catalog id"):
        store.update_policy("coding-fast", next_config)

    assert policy_path.read_text(encoding="utf-8") == baseline


def test_runtime_policy_settings_api_uses_workspace_store(monkeypatch, tmp_path):
    from src.runtime_policy import settings_store

    _copy_runtime_policy_config(tmp_path)
    monkeypatch.setattr(settings_store, "get_workspace_root", lambda: str(tmp_path))
    domain = RuntimePolicySettingsApiDomain(SimpleNamespace())

    assert domain.get_settings()["default_policy_id"] == "coding-default"
    assert domain.update_default({"policy_id": "coding-diagnostic"})[
        "default_policy_id"
    ] == "coding-diagnostic"

    with pytest.raises(HTTPException) as exc:
        domain.update_policy("coding-fast", {"config": {"policy_id": "coding-fast"}})

    assert exc.value.status_code == 400
    assert "task_direction" in str(exc.value.detail)
