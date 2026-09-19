"""Opt-in real official release installation and upgrade in an isolated temporary workspace."""
from __future__ import annotations

import os

import pytest

from src.harness import hermes_installation as installer, install_manager as manager
from src.harness.hermes_release import HermesRelease


@pytest.mark.skipif(os.environ.get("AGENTPARK_TEST_HERMES_INSTALL") != "1", reason="Opt-in Git/Python installation")
def test_real_hermes_install_upgrade_uninstall(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "get_workspace_root", lambda: str(tmp_path))
    latest = installer.latest_release
    monkeypatch.setattr(installer, "latest_release", lambda: HermesRelease("v2026.9.11", "0.21.2"))
    installed = manager.mutate_installation("hermes_agent", "install")["harness"]
    assert installed["status"] == "ready", installed
    assert installed["version"] == "0.21.2"
    monkeypatch.setattr(installer, "latest_release", latest)
    checked = manager.check_installation("hermes_agent", include_updates=True)
    assert checked["update_status"] == "available", checked
    session = tmp_path / "node" / ".harness" / "hermes_agent" / "saved.json"
    session.parent.mkdir(parents=True)
    session.write_text("keep", encoding="utf-8")
    upgraded = manager.mutate_installation("hermes_agent", "upgrade")["harness"]
    assert upgraded["version"] == checked["latest_version"], upgraded
    assert upgraded["executable_path"] == installed["executable_path"]
    assert session.read_text(encoding="utf-8") == "keep"
    removed = manager.mutate_installation("hermes_agent", "uninstall")["harness"]
    assert removed["source"] != "managed"
    assert session.read_text(encoding="utf-8") == "keep"
