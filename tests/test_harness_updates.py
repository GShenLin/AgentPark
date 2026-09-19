from __future__ import annotations

from dataclasses import asdict
import json
from types import SimpleNamespace

import pytest

from src.harness import install_manager as manager, updates
from src.harness.jobs import HarnessJobs
from src.harness.registry import descriptor
from src.web_backend.harness_api import HarnessApiDomain, HarnessOperation


@pytest.mark.parametrize(("older", "newer"), [
    ("1.9.0", "1.10.0"), ("1.0.0-rc.2", "1.0.0-rc.10"),
    ("1.0.0-rc.10", "1.0.0"), ("1.0.0-alpha", "1.0.0-alpha.1"),
    ("1.0.0-alpha.9", "1.0.0-alpha.beta"), ("2026.9.4", "2026.10.1"),
])
def test_semver_precedence(older, newer):
    assert updates.version_key(older) < updates.version_key(newer)


def test_build_metadata_does_not_offer_an_update():
    assert updates.version_key("1.0.0+new") == updates.version_key("1.0.0+old")


@pytest.mark.parametrize("invalid", ["v1.0.0", "1.2", "01.2.3", "1.0.0-01", "1.0.0;command", [], None])
def test_invalid_registry_version_is_rejected(invalid):
    with pytest.raises(ValueError, match="semantic version"):
        updates.version_key(invalid)


@pytest.mark.parametrize(("harness_id", "output", "expected"), [
    ("codex", "codex-cli 0.145.0", "0.145.0"),
    ("claude", "2.1.91 (Claude Code)", "2.1.91"),
    ("openclaw", "OpenClaw 2026.9.4 (3a9d69d)", "2026.9.4"),
    ("pi", "0.85.1", "0.85.1"), ("deepseek_harness", "0.1.5-rc.1", "0.1.5-rc.1"),
])
def test_declared_external_version_formats(tmp_path, harness_id, output, expected):
    assert updates.installed_version(harness_id, tmp_path, output) == expected
    with pytest.raises(ValueError, match="Unrecognized"):
        updates.installed_version(harness_id, tmp_path, "warning 1.0.0\n" + output)


def write_package(root, version):
    package = root / "node_modules" / descriptor("pi").package
    package.mkdir(parents=True, exist_ok=True)
    (package / "cli.js").write_text("", encoding="utf-8")
    (package / "package.json").write_text(json.dumps({
        "name": descriptor("pi").package, "version": version, "bin": {"pi": "cli.js"},
    }), encoding="utf-8")


def test_managed_package_version_is_authoritative(tmp_path):
    write_package(tmp_path, "1.0.0")
    assert updates.installed_version("pi", tmp_path, "2.0.0") == "1.0.0"


def test_registry_query_is_bounded_and_validates_json(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "npm_argv", lambda: ["node", "npm-cli.js"])
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return '"1.2.3"'
    monkeypatch.setattr(updates, "run_process", run)
    assert updates.latest_version("pi", str(tmp_path)) == "1.2.3"
    argv, options = calls[0]
    assert argv[2:6] == ["view", descriptor("pi").package + "@latest", "version", "--json"]
    assert options == {"cwd": str(tmp_path), "timeout": 20}
    monkeypatch.setattr(updates, "run_process", lambda *args, **kwargs: '["1.2.3"]')
    with pytest.raises(ValueError, match="semantic version"):
        updates.latest_version("pi", str(tmp_path))


@pytest.mark.parametrize(("current", "latest", "expected"), [
    ("1.0.0", "1.1.0", "available"), ("1.1.0", "1.1.0", "current"),
    ("2.0.0", "1.1.0", "current"), ("1.0.0-rc.1", "1.0.0", "available"),
])
def test_update_states(tmp_path, monkeypatch, current, latest, expected):
    monkeypatch.setattr(updates, "latest_version", lambda *args: latest)
    result = updates.check_updates("pi", tmp_path, {"version": current}, cwd=str(tmp_path))
    assert result == asdict(updates.HarnessUpdate(current, latest, expected))


def test_network_failure_preserves_ready_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "get_workspace_root", lambda: str(tmp_path))
    write_package(manager.install_root("pi"), "1.0.0")
    monkeypatch.setattr(manager, "command_argv", lambda key: ["node", "cli.js"])
    monkeypatch.setattr(manager, "run_process", lambda *args, **kwargs: "1.0.0")
    def fail(*args):
        raise TimeoutError("Registry request timed out")
    monkeypatch.setattr(updates, "latest_version", fail)
    result = manager.check_installation("pi", include_updates=True)
    assert result["status"] == "ready"
    assert result["error"] == ""
    assert result["update_status"] == "error"
    assert result["update_error"] == "Registry request timed out"
    assert result["installed_version"] == "1.0.0"


@pytest.fixture
def upgrade_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "get_workspace_root", lambda: str(tmp_path))
    root = manager.install_root("pi")
    write_package(root, "1.0.0")
    monkeypatch.setattr(manager, "command_argv", lambda key: ["node", "cli.js"])
    monkeypatch.setattr(manager, "npm_argv", lambda: ["node", "npm-cli.js"])
    monkeypatch.setattr(manager, "latest_version", lambda *args: "1.1.0")
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        if "--version" in argv:
            return updates.installed_version("pi", root, "")
        write_package(root, "1.1.0")
        return "upgraded"
    monkeypatch.setattr(manager, "run_process", run)
    return root, calls


def test_upgrade_installs_exact_newer_release_and_probes_it(upgrade_setup):
    root, calls = upgrade_setup
    marker = root / "session-kept"
    marker.write_text("conversation", encoding="utf-8")
    result = manager.mutate_installation("pi", "upgrade")
    install = calls[1]
    assert install[2] == "install"
    assert "--save-exact" in install and "--engine-strict" in install
    assert install[-1] == descriptor("pi").package + "@1.1.0"
    assert str(root) in install
    assert result["harness"]["version"] == "1.1.0"
    assert result["harness"]["source"] == "managed"
    assert calls[-1][-1] == "--version"
    assert marker.read_text(encoding="utf-8") == "conversation"


@pytest.mark.parametrize("latest", ["1.0.0", "0.9.0"])
def test_upgrade_rejects_stale_or_downgrade_request(upgrade_setup, monkeypatch, latest):
    _, calls = upgrade_setup
    monkeypatch.setattr(manager, "latest_version", lambda *args: latest)
    with pytest.raises(ValueError, match="No newer release"):
        manager.mutate_installation("pi", "upgrade")
    assert len(calls) == 1
    assert "pi" not in manager._MUTATING


def test_failed_upgrade_is_a_failed_job_and_releases_lock(upgrade_setup, monkeypatch):
    def fail(argv, **kwargs):
        if "--version" in argv:
            return "1.0.0"
        raise RuntimeError("npm EBADENGINE")
    monkeypatch.setattr(manager, "run_process", fail)
    job = {"harness_id": "pi", "action": "upgrade", "status": "running"}
    HarnessJobs()._run(job)
    assert job["status"] == "failed"
    assert "EBADENGINE" in job["error"]
    assert "pi" not in manager._MUTATING
    with manager.runtime_lease("pi"):
        pass


def test_upgrade_rejects_wrong_installed_version(upgrade_setup, monkeypatch):
    monkeypatch.setattr(manager, "run_process", lambda *args, **kwargs: "1.0.0")
    with pytest.raises(RuntimeError, match="expected 1.1.0, found 1.0.0"):
        manager.mutate_installation("pi", "upgrade")


def test_external_upgrade_updates_original_without_managed_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "get_workspace_root", lambda: str(tmp_path / "workspace"))
    external = tmp_path / "external"
    write_package(external, "1.0.0")
    launcher = external / "pi.cmd"
    launcher.write_text("@echo off", encoding="utf-8")
    root = manager.install_root("pi")
    monkeypatch.setattr(manager, "command_argv", lambda key: ["node", "external-cli.js"])
    monkeypatch.setattr(manager.shutil, "which", lambda name: str(launcher))
    from src.harness.installation import external_npm_installation
    monkeypatch.setattr(manager, "upgrade_installation", lambda key, root: external_npm_installation(key, str(launcher), windows=True))
    monkeypatch.setattr(manager, "npm_argv", lambda: ["node", "npm-cli.js"])
    monkeypatch.setattr(manager, "latest_version", lambda *args: "1.1.0")
    def run(argv, **kwargs):
        if "--version" in argv:
            return updates.installed_version("pi", external, "")
        assert str(external) in argv
        assert "--global" in argv
        assert str(root) not in argv
        write_package(external, "1.1.0")
        return "updated external installation"
    monkeypatch.setattr(manager, "run_process", run)
    result = manager.mutate_installation("pi", "upgrade")
    assert result["harness"]["source"] == "external"
    assert result["harness"]["can_upgrade"] is True
    assert result["harness"]["can_uninstall"] is False
    assert updates.installed_version("pi", external, "") == "1.1.0"
    assert not root.exists()


def test_active_turn_blocks_upgrade(upgrade_setup):
    _, calls = upgrade_setup
    with manager.runtime_lease("pi"):
        with pytest.raises(RuntimeError, match="busy"):
            manager.mutate_installation("pi", "upgrade")
    assert not calls


def test_upgrade_api_contract_and_dispatch(monkeypatch):
    operation = HarnessOperation(action="upgrade")
    domain = HarnessApiDomain(SimpleNamespace())
    monkeypatch.setattr(domain, "_require_owner", lambda request: None)
    monkeypatch.setattr(domain._jobs, "start", lambda key, action: {"harness_id": key, "action": action})
    assert domain.operate_harness("pi", operation, None) == {"harness_id": "pi", "action": "upgrade"}
    with pytest.raises(ValueError):
        HarnessOperation(action="upgrade", version="untrusted")
