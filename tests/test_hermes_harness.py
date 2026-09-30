from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from src.harness import hermes_installation as installer, hermes_release
from src.harness import install_manager as manager
from src.harness.adapters.hermes_agent import HermesEvents
from src.harness.events import HarnessEvents
from src.harness.hermes_release import HermesRelease


def test_release_calendar_tag_uses_package_version(monkeypatch):
    responses = iter([
        json.dumps({"tag_name": "v2026.9.14", "draft": False, "prerelease": False}).encode(),
        b'[project]\nname="hermes-agent"\nversion="0.21.3"',
    ])
    monkeypatch.setattr(hermes_release, "read_url", lambda url: next(responses))
    assert hermes_release.latest_release() == HermesRelease("v2026.9.14", "0.21.3")


@pytest.mark.parametrize("payload", [
    {}, {"tag_name": "../../bad", "draft": False, "prerelease": False},
    {"tag_name": "v2026.9.14", "draft": True, "prerelease": False},
])
def test_invalid_release_cannot_be_used_as_git_ref(monkeypatch, payload):
    monkeypatch.setattr(hermes_release, "read_url", lambda url: json.dumps(payload).encode())
    with pytest.raises(ValueError):
        hermes_release.latest_release()


@pytest.fixture
def installed(tmp_path, monkeypatch):
    monkeypatch.setattr("src.harness.hermes_python.is_android", lambda: False)
    root = tmp_path / "managed"
    source = root / "source"
    (source / ".git").mkdir(parents=True)
    (source / "pyproject.toml").write_text('[project]\nname="hermes-agent"\nversion="0.21.2"', encoding="utf-8")
    python = installer.python_path(root / ".venv")
    python.parent.mkdir(parents=True)
    python.touch()
    probe = {"source": str(source), "version": "0.21.2", "prefix": str(root / ".venv")}
    monkeypatch.setattr(installer, "run_process", lambda *args, **kwargs: json.dumps(probe))
    monkeypatch.setattr(installer, "_git", lambda source, *args: hermes_release.REPOSITORY if args[0] == "remote" else "")
    monkeypatch.setattr(installer, "latest_release", lambda: HermesRelease("v2026.9.14", "0.21.3"))
    return root, source, python, probe


def test_check_separates_runtime_health_and_release_failure(installed, monkeypatch):
    root, _, _, _ = installed
    info = installer.check(root, include_updates=True)
    assert info["status"] == "ready" and info["update_status"] == "available"
    assert info["can_upgrade"] and info["can_uninstall"]
    def offline():
        raise TimeoutError("GitHub unavailable")
    monkeypatch.setattr(installer, "latest_release", offline)
    info = installer.check(root, include_updates=True)
    assert info["status"] == "ready" and info["update_status"] == "error"
    assert info["update_error"] == "GitHub unavailable"


def test_unknown_source_never_queries_official_release(installed, monkeypatch):
    root, _, _, _ = installed
    monkeypatch.setattr(installer, "_git", lambda *args: "https://example.com/fork.git")
    monkeypatch.setattr(installer, "latest_release", lambda: pytest.fail("Unverified source must not query releases"))
    info = installer.check(root, include_updates=True)
    assert info["status"] == "ready"
    assert info["can_upgrade"] is False
    assert info["update_status"] == "error"
    assert info["latest_version"] == ""
    assert info["update_error"] == info["upgrade_error"]
    with pytest.raises(ValueError, match="official NousResearch"):
        installer.mutate(root, "upgrade")


def test_incomplete_environment_reports_reinstall(installed):
    root, _, python, _ = installed
    python.unlink()
    info = installer.check(root, include_updates=True)
    assert info["status"] == "error"
    assert "Reinstall" in info["error"]
    assert info["can_uninstall"] is True


def test_external_upgrade_targets_original_python_and_source(installed, monkeypatch):
    root, source, python, probe = installed
    managed = root.parent / "workspace-copy"
    monkeypatch.setattr(installer, "locate", lambda root: installer.HermesInstallation(python, source, False))
    monkeypatch.setattr(installer, "_uv", lambda root, output: ["uv"])
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return json.dumps({**probe, "version": "0.21.3"}) if "-c" in argv else "installed"
    monkeypatch.setattr(installer, "run_process", run)
    installer.mutate(managed, "upgrade")
    install = calls[0]
    assert install == ["uv", "pip", "install", "--python", str(python), "-e", str(source)]
    assert not managed.exists()


def test_android_upgrade_uses_native_installer_without_uv(installed, monkeypatch):
    root, source, python, probe = installed
    monkeypatch.setattr("src.harness.hermes_python.is_android", lambda: True)
    calls = []
    monkeypatch.setattr("src.harness.hermes_python.install_android",
                        lambda python, source, output: calls.append((python, source)))
    monkeypatch.setattr(installer, "_uv", lambda *args: pytest.fail("Android must not bootstrap uv"))
    probe["version"] = "0.21.3"
    installer.mutate(root, "upgrade")
    assert calls == [(python, source)]


def test_upgrade_refuses_dirty_source_before_checkout(installed, monkeypatch):
    root, _, _, _ = installed
    calls = []
    def git(source, *args):
        calls.append(args)
        return hermes_release.REPOSITORY if args[0] == "remote" else " M user-change.py"
    monkeypatch.setattr(installer, "_git", git)
    with pytest.raises(ValueError, match="local changes"):
        installer.mutate(root, "upgrade")
    assert not any(args[0] in {"fetch", "checkout"} for args in calls)


def test_managed_uninstall_preserves_node_sessions(installed):
    root, _, _, _ = installed
    session = root.parent / "node" / ".harness" / "hermes_agent" / "conversation.json"
    session.parent.mkdir(parents=True)
    session.write_text("saved", encoding="utf-8")
    installer.mutate(root, "uninstall")
    assert not root.exists()
    assert session.read_text(encoding="utf-8") == "saved"


def test_external_cannot_be_uninstalled(tmp_path):
    with pytest.raises(ValueError, match="managed"):
        installer.mutate(tmp_path / "missing", "uninstall")


@pytest.mark.parametrize("layout", ["console", "posix-wrapper", "windows-copied", "windows-delegator"])
def test_locate_external_hermes_without_creating_workspace_copy(tmp_path, monkeypatch, layout):
    if layout.startswith("windows") and os.name != "nt":
        pytest.skip("Native Windows launcher layout")
    source = tmp_path / "hermes-agent"
    environment = source / "venv"
    python = installer.python_path(environment)
    python.parent.mkdir(parents=True)
    python.touch()
    (environment / "pyvenv.cfg").write_text("home = external", encoding="utf-8")
    if layout == "console":
        launcher = python.parent / ("hermes.exe" if os.name == "nt" else "hermes")
        launcher.touch()
    else:
        launchers = tmp_path / "bin"
        launchers.mkdir()
        if layout == "posix-wrapper":
            launcher = launchers / "hermes"
            launcher.write_text('#!/usr/bin/env bash\nunset PYTHONPATH\nunset PYTHONHOME\n'
                                f'exec "{python}" "{source / "hermes"}" "$@"\n', encoding="utf-8")
        elif layout == "windows-copied":
            launcher = launchers / "hermes.exe"
            launcher.touch()
        else:
            launcher = launchers / "hermes.cmd"
            launcher.write_text(f'@echo off\n"{python.parent / "hermes.exe"}" %*\n', encoding="utf-8")
    monkeypatch.setattr(installer.shutil, "which", lambda name: str(launcher))
    monkeypatch.setattr(installer, "run_process", lambda *args, **kwargs: json.dumps({
        "source": str(source), "version": "0.21.3", "prefix": str(environment),
    }))
    root = tmp_path / "workspace-copy"
    found = installer.locate(root)
    assert found == installer.HermesInstallation(python, source, False)
    assert not root.exists()


def test_external_system_python_is_rejected(tmp_path, monkeypatch):
    python = tmp_path / ("python.exe" if os.name == "nt" else "python")
    python.touch()
    launcher = tmp_path / ("hermes.exe" if os.name == "nt" else "hermes")
    launcher.touch()
    monkeypatch.setattr(installer.shutil, "which", lambda name: str(launcher))
    monkeypatch.setattr(installer, "run_process", lambda *args, **kwargs: json.dumps({
        "source": str(tmp_path), "version": "0.21.3", "prefix": str(tmp_path.parent),
    }))
    with pytest.raises(ValueError, match="own virtual environment"):
        installer.locate(tmp_path / "workspace-copy")


def test_hermes_uses_python_backend_and_existing_exclusion(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "get_workspace_root", lambda: str(tmp_path))
    calls = []
    monkeypatch.setattr(installer, "mutate", lambda root, action: calls.append((root, action)) or "ok")
    monkeypatch.setattr(installer, "check", lambda root, **kwargs: {"status": "ready", "error": ""})
    manager.mutate_installation("hermes_agent", "install")
    assert calls[0] == (manager.install_root("hermes_agent"), "install")
    with manager.runtime_lease("hermes_agent"):
        with pytest.raises(RuntimeError, match="busy"):
            manager.mutate_installation("hermes_agent", "upgrade")


def test_hermes_events_stream_reasoning_tools_and_final():
    emitted = []
    events = HarnessEvents("hermes_agent", "p", emitted.append)
    parser = HermesEvents(events)
    for event in [
        {"type": "thinking", "text": "reason"}, {"type": "text", "text": "hello"},
        {"type": "tool_start", "id": "1", "name": "read_file", "arguments": {"path": "x"}},
        {"type": "tool_end", "id": "1", "name": "read_file", "output": "file", "error": False},
        {"type": "result", "text": "done"},
    ]:
        parser.handle(json.dumps(event))
    assert parser.result == "done"
    assert events.thinking == "reason"
    assert [event["type"] for event in emitted] == ["node_thinking_delta", "node_message_delta", "tool_call_start", "tool_call_end"]
    with pytest.raises(ValueError, match="after its result"):
        parser.handle('{"type":"text","text":"late"}')


@pytest.mark.parametrize("event", [
    {"type": "result", "text": []}, {"type": "text"}, {"type": "unknown"},
    {"type": "tool_end", "id": "unstarted", "name": "read", "output": ""},
])
def test_hermes_rejects_malformed_events(event):
    with pytest.raises(ValueError):
        HermesEvents(HarnessEvents("hermes_agent", "p", None)).handle(json.dumps(event))
