"""Opt-in npm upgrades in temporary workspace and external prefixes; no model calls."""
from __future__ import annotations

import os

import pytest

from src.harness import install_manager as manager, updates
from src.harness.process import run_process
from src.harness.registry import descriptor


@pytest.mark.skipif(not os.environ.get("AGENTPARK_TEST_PI_UPGRADE_FROM"), reason="Set an older Pi npm version to enable")
def test_real_managed_upgrade(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "get_workspace_root", lambda: str(tmp_path))
    old = os.environ["AGENTPARK_TEST_PI_UPGRADE_FROM"]
    updates.version_key(old)
    root = manager.install_root("pi")
    root.mkdir(parents=True)
    run_process([*manager.npm_argv(), "install", "--prefix", str(root), "--save-exact", "--engine-strict",
                 "--no-audit", "--no-fund", descriptor("pi").package + "@" + old], cwd=str(root), timeout=900)
    before = manager.check_installation("pi", include_updates=True)
    assert before["status"] == "ready", before
    assert before["update_status"] == "available", before
    marker = tmp_path / "node" / ".harness" / "conversation.jsonl"
    marker.parent.mkdir(parents=True)
    marker.write_text('{"text":"preserve me"}\n', encoding="utf-8")
    result = manager.mutate_installation("pi", "upgrade")
    assert result["harness"]["status"] == "ready", result
    after = manager.check_installation("pi", include_updates=True)
    assert after["update_status"] == "current", after
    assert updates.version_key(after["installed_version"]) > updates.version_key(old)
    assert marker.read_text(encoding="utf-8") == '{"text":"preserve me"}\n'
    assert manager.mutate_installation("pi", "uninstall")["harness"]["source"] != "managed"


@pytest.mark.skipif(not os.environ.get("AGENTPARK_TEST_PI_UPGRADE_FROM"), reason="Set an older Pi npm version to enable")
def test_real_external_upgrade_in_place(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(manager, "get_workspace_root", lambda: str(workspace))
    prefix = tmp_path / "external npm"
    prefix.mkdir()
    old = os.environ["AGENTPARK_TEST_PI_UPGRADE_FROM"]
    updates.version_key(old)
    run_process([*manager.npm_argv(), "install", "--global", "--prefix", str(prefix), "--engine-strict",
                 "--no-audit", "--no-fund", descriptor("pi").package + "@" + old], cwd=str(prefix), timeout=900)
    bin_dir = prefix if os.name == "nt" else prefix / "bin"
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    before = manager.check_installation("pi", include_updates=True)
    assert before["status"] == "ready", before
    assert before["source"] == "external", before
    assert before["can_upgrade"] is True, before
    assert before["update_status"] == "available", before
    marker = prefix / "conversation.jsonl"
    marker.write_text("preserve session", encoding="utf-8")
    result = manager.mutate_installation("pi", "upgrade")
    after = result["harness"]
    assert after["status"] == "ready", result
    assert after["source"] == "external", result
    assert after["executable_path"] == before["executable_path"]
    assert after["version"] != before["version"]
    assert marker.read_text(encoding="utf-8") == "preserve session"
    assert not manager.install_root("pi").exists()
    assert manager.check_installation("pi", include_updates=True)["update_status"] == "current"
    run_process([*manager.npm_argv(), "uninstall", "--global", "--prefix", str(prefix),
                 "--no-audit", "--no-fund", descriptor("pi").package], cwd=str(prefix), timeout=900)
