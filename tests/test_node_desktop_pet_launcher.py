from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.web_backend import node_desktop_pet_launcher as launcher


def test_desktop_pet_base_url_uses_loopback_for_wildcard_bind_host():
    assert (
        launcher._desktop_pet_base_url(
            {
                "AGENTPARK_SERVER_HOST": "0.0.0.0",
                "AGENTPARK_SERVER_PORT": "8788",
            }
        )
        == "http://127.0.0.1:8788"
    )


def test_launch_node_desktop_pet_process_starts_electron_directly(monkeypatch, tmp_path):
    launcher._PROCESS_IDS.clear()
    pet_dir = tmp_path / "desktop" / "pet"
    pet_dir.mkdir(parents=True)
    (pet_dir / "package.json").write_text("{}", encoding="utf-8")
    electron_path = Path(launcher._electron_launch_path(str(pet_dir)))
    electron_path.parent.mkdir(parents=True)
    electron_path.write_text("", encoding="utf-8")
    captured = {}

    class FakeProcess:
        pid = 42

        def wait(self, timeout):
            raise launcher.subprocess.TimeoutExpired("electron", timeout)

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(launcher, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)

    process = launcher.launch_node_desktop_pet_process("default", "GPT", {"pinned": True})

    assert process.pid == 42
    assert captured["args"][0:2] == [str(electron_path), "."]
    assert any(str(item).startswith("--agentpark-request=") for item in captured["args"])
    assert len(captured["args"]) == 3
    assert captured["kwargs"]["cwd"] == str(pet_dir)
    assert captured["kwargs"]["env"]["AGENTPARK_OWNER_PID"] == str(launcher.os.getpid())
    assert captured["kwargs"]["env"]["AGENTPARK_BASE_URL"].startswith("http://")
    assert 42 in launcher._PROCESS_IDS
    launcher._PROCESS_IDS.clear()


def test_terminate_registered_desktop_pet_processes_uses_taskkill_on_windows(monkeypatch):
    launcher._PROCESS_IDS.clear()
    launcher._PROCESS_IDS.update({1234})
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)

    def fake_kill(pid, signal):
        calls.append((["kill", str(pid), str(signal)], {}))

    monkeypatch.setattr(launcher, "_discover_desktop_pet_process_ids", lambda: set())
    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    monkeypatch.setattr(launcher.os, "kill", fake_kill)

    result = launcher.terminate_registered_desktop_pet_processes()

    assert result["requested"] == 1
    if launcher.os.name == "nt":
        assert calls[0][0] == ["taskkill", "/PID", "1234", "/T", "/F"]
    else:
        assert result["terminated"] == [1234]
    assert launcher._PROCESS_IDS == set()


def test_ensure_desktop_pet_dependencies_installs_when_electron_is_missing(monkeypatch, tmp_path):
    pet_dir = tmp_path / "desktop" / "pet"
    log_dir = tmp_path / ".runtime"
    pet_dir.mkdir(parents=True)
    log_dir.mkdir()
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        electron_path = Path(launcher._electron_launch_path(str(pet_dir)))
        electron_path.parent.mkdir(parents=True)
        electron_path.write_text("", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    launcher._ensure_desktop_pet_dependencies(str(pet_dir), "npm.cmd", str(log_dir))

    assert calls
    assert calls[0][0] == ["npm.cmd", "install"]
    assert calls[0][1]["cwd"] == str(pet_dir)


def test_ensure_desktop_pet_dependencies_reports_install_failure(monkeypatch, tmp_path):
    pet_dir = tmp_path / "desktop" / "pet"
    log_dir = tmp_path / ".runtime"
    pet_dir.mkdir(parents=True)
    log_dir.mkdir()

    def fake_run(args, **kwargs):
        kwargs["stderr"].write("electron download failed".encode("utf-8"))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    with pytest.raises(HTTPException) as exc_info:
        launcher._ensure_desktop_pet_dependencies(str(pet_dir), "npm.cmd", str(log_dir))

    assert exc_info.value.status_code == 500
    assert "desktop pet dependency install failed with code 7" in exc_info.value.detail
    assert "electron download failed" in exc_info.value.detail
