from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.harness import install_manager as manager
from src.harness.installation import external_npm_installation
from src.harness.registry import descriptor


def package(base):
    root = base / "node_modules" / descriptor("pi").package
    root.mkdir(parents=True)
    entry = root / "cli.js"
    entry.write_text("", encoding="utf-8")
    (root / "package.json").write_text(json.dumps({
        "name": descriptor("pi").package, "version": "1.0.0", "bin": {"pi": "cli.js"},
    }), encoding="utf-8")
    return entry


def test_windows_global_prefix_comes_from_launcher_not_environment(tmp_path):
    prefix = tmp_path / "original npm prefix"
    package(prefix)
    launcher = prefix / "pi.cmd"
    launcher.touch()
    result = external_npm_installation("pi", str(launcher), windows=True)
    assert result.prefix == prefix
    assert result.package_base == prefix
    assert result.scope_args() == ["--global", "--prefix", str(prefix)]


def test_windows_local_install_preserves_local_scope(tmp_path):
    package(tmp_path)
    launcher = tmp_path / "node_modules" / ".bin" / "pi.cmd"
    launcher.parent.mkdir()
    launcher.touch()
    result = external_npm_installation("pi", str(launcher), windows=True)
    assert result.prefix == tmp_path
    assert result.scope_args() == ["--global=false", "--prefix", str(tmp_path)]


def mock_symlink(monkeypatch, launcher, entry):
    # Exercise POSIX resolution on Windows without requiring symlink creation privileges.
    original_resolve = Path.resolve
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == launcher or original_is_symlink(path))
    monkeypatch.setattr(Path, "resolve", lambda path, *args, **kwargs:
                        entry if path == launcher else original_resolve(path, *args, **kwargs))


def test_posix_global_layout_validates_symlink_target(tmp_path, monkeypatch):
    entry = package(tmp_path / "lib")
    launcher = tmp_path / "bin" / "pi"
    launcher.parent.mkdir()
    mock_symlink(monkeypatch, launcher, entry)
    result = external_npm_installation("pi", str(launcher), windows=False)
    assert result.prefix == tmp_path
    assert result.package_base == tmp_path / "lib"
    assert result.global_install is True
    other = tmp_path / "other"
    other.touch()
    mock_symlink(monkeypatch, launcher, other)
    with pytest.raises(ValueError, match="does not target"):
        external_npm_installation("pi", str(launcher), windows=False)


def test_posix_local_layout(tmp_path, monkeypatch):
    entry = package(tmp_path)
    launcher = tmp_path / "node_modules" / ".bin" / "pi"
    launcher.parent.mkdir()
    mock_symlink(monkeypatch, launcher, entry)
    result = external_npm_installation("pi", str(launcher), windows=False)
    assert result.prefix == tmp_path
    assert result.global_install is False


def test_unknown_native_installation_is_not_converted_to_workspace_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "get_workspace_root", lambda: str(tmp_path))
    executable = tmp_path / "pi.exe"
    executable.touch()
    monkeypatch.setattr(manager.shutil, "which", lambda name: str(executable))
    monkeypatch.setattr(manager, "run_process", lambda *args, **kwargs: "1.0.0")
    info = manager.check_installation("pi")
    assert info["status"] == "ready"
    assert info["can_upgrade"] is False
    assert "original installer" in info["upgrade_error"]
    with pytest.raises(ValueError, match="original installer"):
        manager.mutate_installation("pi", "upgrade")
    assert not manager.install_root("pi").exists()


def test_external_permission_failure_does_not_create_workspace_copy(tmp_path, monkeypatch):
    prefix = tmp_path / "external"
    package(prefix)
    launcher = prefix / "pi.cmd"
    launcher.touch()
    monkeypatch.setattr(manager, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(manager.shutil, "which", lambda name: str(launcher))
    monkeypatch.setattr(manager, "upgrade_installation", lambda key, root: external_npm_installation(key, str(launcher), windows=True))
    monkeypatch.setattr(manager, "command_argv", lambda key: ["node", "pi.js"])
    monkeypatch.setattr(manager, "npm_argv", lambda: ["npm"])
    monkeypatch.setattr(manager, "latest_version", lambda *args: "1.1.0")
    def run(argv, **kwargs):
        if "--version" in argv:
            return "1.0.0"
        raise PermissionError("Access denied to external prefix")
    monkeypatch.setattr(manager, "run_process", run)
    with pytest.raises(PermissionError, match="Access denied"):
        manager.mutate_installation("pi", "upgrade")
    assert not manager.install_root("pi").exists()
    assert "pi" not in manager._MUTATING
