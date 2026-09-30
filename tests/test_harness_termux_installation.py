"""Android Codex distribution identity must survive detection, checks and upgrades."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.harness import install_manager as manager, updates
from src.harness.installation import external_npm_installation

TERMUX_PACKAGE = "@mmmbuto/codex-cli-termux"


def write_package(base, name, version="0.153.3"):
    root = base / "node_modules" / name
    (root / "bin").mkdir(parents=True, exist_ok=True)
    entry = root / "bin" / "codex.js"
    entry.write_text("", encoding="utf-8")
    (root / "package.json").write_text(json.dumps({
        "name": name, "version": version, "bin": {"codex": "bin/codex.js"},
    }), encoding="utf-8")
    return entry


@pytest.fixture(params=["global", "local"])
def termux_installation(tmp_path, monkeypatch, request):
    prefix = tmp_path / "data" / "data" / "com.termux" / "files" / "usr"
    global_install = request.param == "global"
    base = prefix / "lib" if global_install else prefix
    entry = write_package(base, TERMUX_PACKAGE)
    launcher = (prefix / "bin" if global_install else prefix / "node_modules" / ".bin") / "codex"
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    # Simulate POSIX symlinks on Windows without requiring elevated privileges.
    resolve = Path.resolve
    is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "resolve", lambda path, *args, **kwargs:
                        entry if path == launcher else resolve(path, *args, **kwargs))
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == launcher or is_symlink(path))
    monkeypatch.setattr(manager, "get_workspace_root", lambda: str(tmp_path / "workspace"))
    monkeypatch.setattr(manager.shutil, "which", lambda name: str(launcher) if name == "codex" else None)
    monkeypatch.setattr(manager, "upgrade_installation", lambda key, root:
                        external_npm_installation(key, str(launcher), windows=False))
    return prefix, base, launcher, global_install


def test_launcher_selects_termux_package_even_with_official_package_present(termux_installation):
    prefix, base, launcher, global_install = termux_installation
    write_package(base, "@openai/codex", "0.155.1")
    found = external_npm_installation("codex", str(launcher), windows=False)
    assert found.package == TERMUX_PACKAGE
    assert found.prefix == prefix
    assert found.package_base == base
    assert found.global_install is global_install


@pytest.mark.parametrize("latest,state", [("0.153.3", "current"), ("0.153.4", "available")])
def test_check_queries_installed_distribution(termux_installation, monkeypatch, latest, state):
    _, _, launcher, _ = termux_installation
    monkeypatch.setattr(manager, "run_process", lambda *args, **kwargs: "codex-cli 0.153.3")
    monkeypatch.setattr(updates, "npm_argv", lambda: ["npm"])
    queries = []

    def registry(argv, **kwargs):
        queries.append(argv)
        return json.dumps(latest)

    monkeypatch.setattr(updates, "run_process", registry)
    result = manager.check_installation("codex", include_updates=True)
    assert result["status"] == "ready"
    assert result["source"] == "external"
    assert result["executable_path"] == str(launcher)
    assert result["package"] == TERMUX_PACKAGE
    assert result["can_upgrade"] is True
    assert result["can_uninstall"] is False
    assert result["error"] == result["upgrade_error"] == result["update_error"] == ""
    assert result["installed_version"] == "0.153.3"
    assert result["latest_version"] == latest
    assert result["update_status"] == state
    assert queries[0][1:4] == ["view", TERMUX_PACKAGE + "@latest", "version"]


def test_upgrade_preserves_termux_package_prefix_scope_and_sessions(termux_installation, monkeypatch):
    prefix, base, _, global_install = termux_installation
    marker = prefix / "session.json"
    marker.write_text("preserve", encoding="utf-8")
    monkeypatch.setattr(manager, "npm_argv", lambda: ["npm"])
    monkeypatch.setattr(updates, "npm_argv", lambda: ["npm"])
    queries = []
    installs = []

    def registry(argv, **kwargs):
        queries.append(argv)
        return '"0.153.4"'

    def run(argv, **kwargs):
        if "--version" in argv:
            version = updates.installed_version("codex", base, "", package=TERMUX_PACKAGE)
            return "codex-cli " + version
        installs.append(argv)
        assert kwargs["cwd"] == str(prefix)
        write_package(base, TERMUX_PACKAGE, "0.153.4")
        return "updated"

    monkeypatch.setattr(updates, "run_process", registry)
    monkeypatch.setattr(manager, "run_process", run)
    result = manager.mutate_installation("codex", "upgrade")
    assert queries[0][2] == TERMUX_PACKAGE + "@latest"
    assert len(installs) == 1
    assert installs[0][-1] == TERMUX_PACKAGE + "@0.153.4"
    assert installs[0][2:5] == ["--global" if global_install else "--global=false", "--prefix", str(prefix)]
    assert result["harness"]["package"] == TERMUX_PACKAGE
    assert result["harness"]["source"] == "external"
    assert result["harness"]["version"] == "codex-cli 0.153.4"
    assert marker.read_text(encoding="utf-8") == "preserve"
    assert not manager.install_root("codex").exists()
    assert not (base / "node_modules" / "@openai" / "codex").exists()


@pytest.mark.parametrize("invalid", ["missing", "wrong-name", "wrong-bin", "escape"])
def test_invalid_termux_package_remains_an_explicit_error(termux_installation, monkeypatch, invalid):
    _, base, launcher, _ = termux_installation
    manifest = base / "node_modules" / TERMUX_PACKAGE / "package.json"
    if invalid == "missing":
        manifest.unlink()
        expected = "manifest is missing"
    else:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if invalid == "wrong-name":
            data["name"] = "@openai/codex"
            expected = "Unexpected Harness package manifest"
        elif invalid == "wrong-bin":
            (manifest.parent / "other.js").touch()
            data["bin"]["codex"] = "other.js"
            expected = "does not target its declared npm entry"
        else:
            data["bin"]["codex"] = "../../../escape.js"
            expected = "Invalid Harness executable"
        manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match=expected):
        external_npm_installation("codex", str(launcher), windows=False)
    monkeypatch.setattr(manager, "run_process", lambda *args, **kwargs: "codex-cli 0.153.3")
    monkeypatch.setattr(updates, "latest_version", lambda *args: pytest.fail("Must not query another distribution"))
    result = manager.check_installation("codex", include_updates=True)
    assert result["status"] == "ready"
    assert result["can_upgrade"] is False
    assert result["update_status"] == "error"
    assert result["latest_version"] == ""
    assert expected in result["upgrade_error"]


def test_unknown_symlink_does_not_probe_official_package(tmp_path, monkeypatch):
    launcher = tmp_path / "bin" / "codex"
    target = tmp_path / "native" / "codex"
    resolve = Path.resolve
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == launcher)
    monkeypatch.setattr(Path, "resolve", lambda path, *args, **kwargs:
                        target if path == launcher else resolve(path, *args, **kwargs))
    with pytest.raises(ValueError, match="original installer") as error:
        external_npm_installation("codex", str(launcher), windows=False)
    assert str(target) in str(error.value)
    assert "No such file" not in str(error.value)
