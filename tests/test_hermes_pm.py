"""PM upgrades must preserve the selected installation until the new runtime is verified."""
import json

import pytest

from src.harness import hermes_installation as installer, hermes_pm as pm
from src.harness.hermes_release import HermesRelease, REPOSITORY


GENERATION = "a" * 32
COMMIT = "b" * 40
RELEASE = HermesRelease("v0.21.6", "0.21.6", "pm")


def write_generation(root, generation=GENERATION, version="0.21.6"):
    source, python = pm.generation_paths(root, generation)
    (source / ".git").mkdir(parents=True)
    python.parent.mkdir(parents=True)
    python.touch()
    (source / "pyproject.toml").write_text('[project]\nname="hermes-agent"\nversion="0.0.0"', encoding="utf-8")
    (source / "install-stamp.json").write_text(json.dumps({
        "schemaVersion": 2, "baseVersion": version, "commit": COMMIT, "updateMechanism": "external",
    }), encoding="utf-8")
    return source, python


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    root = tmp_path / "hermes"
    source = root / "source"
    (source / ".git").mkdir(parents=True)
    (source / "pyproject.toml").write_text('[project]\nname="hermes-agent"\nversion="0.21.5"', encoding="utf-8")
    python = installer.python_path(root / ".venv")
    python.parent.mkdir(parents=True)
    python.touch()
    (source / "keep.txt").write_text("original installation", encoding="utf-8")
    monkeypatch.setattr(installer, "latest_release", lambda: RELEASE)
    calls = []

    def git(source, *args):
        calls.append(args)
        return REPOSITORY if args[0] == "remote" else COMMIT if args[0] == "rev-parse" else ""

    monkeypatch.setattr(installer, "_git", git)
    monkeypatch.setattr(installer, "_probe", lambda executable, cwd: {
        "source": str(cwd), "prefix": str(executable.parent.parent),
        "version": "0.21.5" if executable == python else "0.21.6",
    })
    monkeypatch.setattr(installer, "_verify_runtime", lambda *args: None)
    return root, python, calls


def test_successful_migration_switches_only_after_validation(legacy, monkeypatch):
    root, previous, git_calls = legacy
    def prepare(root, release, output):
        assert installer.command(root) == [str(previous)]
        source, python = write_generation(root)
        return GENERATION, source, python
    monkeypatch.setattr(pm, "prepare", prepare)
    def verify(python, source, tooling_root, output):
        assert installer.command(root) == [str(previous)]
    monkeypatch.setattr(installer, "_verify_runtime", verify)
    installer.mutate(root, "upgrade")
    new_source, new_python = pm.generation_paths(root, GENERATION)
    assert installer.command(root) == [str(new_python)]
    assert (root / "source/keep.txt").read_text(encoding="utf-8") == "original installation"
    assert previous.is_file()
    assert not any(args[0] in {"checkout", "fetch", "reset"} for args in git_calls)
    info = installer.check(root, include_updates=True)
    assert info["version"] == "0.21.6" and info["status"] == "ready"
    assert info["update_status"] == "current" and info["latest_version"] == "0.21.6"
    assert installer.validate_source(new_source) == "0.21.6"


@pytest.mark.parametrize("failure", ["build", "probe", "runtime", "publish"])
def test_failed_upgrade_preserves_previous_generation(legacy, monkeypatch, failure):
    root, previous, _ = legacy
    def fail(*args, **kwargs):
        raise RuntimeError("candidate failed")
    def prepare(root, release, output):
        source, python = write_generation(root)
        return GENERATION, source, python
    monkeypatch.setattr(pm, "prepare", fail if failure == "build" else prepare)
    if failure == "probe":
        monkeypatch.setattr(installer, "_probe", fail)
    if failure == "runtime":
        monkeypatch.setattr(installer, "_verify_runtime", fail)
    if failure == "publish":
        monkeypatch.setattr(pm.os, "replace", fail)
    with pytest.raises(RuntimeError, match="candidate failed"):
        installer.mutate(root, "upgrade")
    assert installer.command(root) == [str(previous)]
    assert not (root / "current.json").exists()
    assert not list(root.glob(".current-*.json"))
    assert (root / "source/keep.txt").is_file()


def test_failed_later_update_preserves_existing_selection(legacy, monkeypatch):
    root, _, _ = legacy
    source, python = write_generation(root)
    pm.publish(root, GENERATION, "0.21.6")
    before = (root / "current.json").read_bytes()
    monkeypatch.setattr(installer, "latest_release", lambda: HermesRelease("v0.21.7", "0.21.7", "pm"))
    def fail(*args):
        raise RuntimeError("new environment failed")
    monkeypatch.setattr(pm, "prepare", fail)
    with pytest.raises(RuntimeError, match="new environment failed"):
        installer.mutate(root, "upgrade")
    assert (root / "current.json").read_bytes() == before
    assert installer.command(root) == [str(python)]


@pytest.mark.parametrize("field,value", [("version", "0.0.0"), ("source", "wrong-source"), ("prefix", "wrong-python")])
def test_mismatched_environment_never_activates(legacy, monkeypatch, field, value):
    root, previous, _ = legacy
    def prepare(root, release, output):
        source, python = write_generation(root)
        return GENERATION, source, python
    monkeypatch.setattr(pm, "prepare", prepare)
    monkeypatch.setattr(installer, "_probe", lambda executable, cwd: {
        "source": str(cwd), "prefix": str(executable.parent.parent), "version": "0.21.6", field: value,
    })
    with pytest.raises(RuntimeError, match="environment verification"):
        installer.mutate(root, "upgrade")
    assert installer.command(root) == [str(previous)]


def test_pm_android_refusal_precedes_filesystem_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr("src.harness.hermes_python.is_android", lambda: True)
    root = tmp_path / "not-created"
    with pytest.raises(ValueError, match="Android/Termux"):
        pm.prepare(root, RELEASE, [])
    assert not root.exists()


@pytest.mark.parametrize("generation", ["../outside", "a" * 31, "a" * 33, "C:/outside", None])
def test_selection_rejects_unowned_paths(tmp_path, generation):
    (tmp_path / "current.json").write_text(json.dumps({
        "schema": 1, "generation": generation, "version": "0.21.6",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid managed Hermes generation"):
        installer.locate(tmp_path)


def test_broken_selection_never_falls_back_to_legacy(legacy):
    root, _, _ = legacy
    (root / "current.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="selection"):
        installer.locate(root)


def test_selection_requires_matching_stamp(tmp_path):
    write_generation(tmp_path)
    pm.publish(tmp_path, GENERATION, "0.21.7")
    with pytest.raises(ValueError, match="does not match"):
        pm.selected(tmp_path)


def test_stamp_must_match_git_commit_and_release_tag(tmp_path, monkeypatch):
    source, _ = write_generation(tmp_path)
    monkeypatch.setattr(installer, "_git", lambda path, *args: REPOSITORY if args[0] == "remote" else "c" * 40)
    with pytest.raises(ValueError, match="does not match its checkout"):
        installer.validate_source(source)
    monkeypatch.setattr(installer, "_git", lambda path, *args: (
        REPOSITORY if args[0] == "remote" else COMMIT if args[-1] == "HEAD" else "c" * 40))
    with pytest.raises(ValueError, match="does not match its release tag"):
        installer.validate_source(source)


def test_pm_build_uses_official_locked_builder_and_external_stamp(tmp_path, monkeypatch):
    monkeypatch.setattr(pm.shutil, "which", lambda name: "git")
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if "clone" in argv:
            from pathlib import Path
            source = Path(argv[-1])
            for name in ("pm/build_env.py", "pm/lock.json", "uv.lock", "scripts/write_install_stamp.py"):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
        return "ok"
    monkeypatch.setattr(pm, "run_process", run)
    monkeypatch.setenv("HERMES_INSTALL_ROOT", "foreign")
    monkeypatch.setenv("HERMES_PAYLOAD_TAG", "foreign")
    monkeypatch.setenv("PYTHONPATH", "foreign")
    generation, source, python = pm.prepare(tmp_path, RELEASE, [])
    assert len(calls) == 3
    assert "v0.21.6" in calls[0][0] and REPOSITORY in calls[0][0]
    assert "scripts/write_install_stamp.py" in calls[1][0]
    assert calls[1][0][calls[1][0].index("--update-mechanism") + 1] == "external"
    assert calls[1][0][calls[1][0].index("--base-version") + 1] == "0.21.6"
    assert calls[2][0][3:] == ["-m", "pm.build_env", "--source", str(source), "--out", str(python.parent.parent)]
    for _, kwargs in calls:
        assert "HERMES_INSTALL_ROOT" not in kwargs["env"]
        assert "HERMES_PAYLOAD_TAG" not in kwargs["env"]
        assert "PYTHONPATH" not in kwargs["env"]
        assert kwargs["env"]["HERMES_RUNTIME_DIR"] == str(tmp_path / "tools")
    assert not (tmp_path / "current.json").exists()
