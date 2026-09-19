import os
import subprocess
import sys
import json

import pytest

from src import runtime_environment as runtime


@pytest.fixture(autouse=True)
def reset_environment_cache():
    runtime.get_runtime_environment.cache_clear()
    yield
    runtime.get_runtime_environment.cache_clear()


@pytest.mark.parametrize("platform,shell,executable", [
    ("windows", "powershell", r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"),
    ("linux", "bash", "/bin/bash"),
    ("macos", "zsh", "/bin/zsh"),
    ("termux", "bash", "/data/data/com.termux/files/usr/bin/bash"),
    ("android", "sh", "/system/bin/sh"),
])
def test_detects_host_shell_and_exports_variables(monkeypatch, platform, shell, executable):
    monkeypatch.setattr(runtime, "_detect_platform", lambda: platform)
    monkeypatch.setenv("SHELL", executable if platform != "windows" else "/bin/bash")
    monkeypatch.setenv("AGENTPARK_PLATFORM", "stale-host")
    monkeypatch.setenv("AGENTPARK_SHELL", "stale-shell")
    monkeypatch.setenv("AGENTPARK_SHELL_EXECUTABLE", "stale-path")
    for key in ("PYTHONUTF8", "PYTHONIOENCODING"):
        monkeypatch.delenv(key, raising=False)
    candidates = []

    def which(candidate):
        candidates.append(candidate)
        return executable

    monkeypatch.setattr(runtime.shutil, "which", which)
    env = runtime.initialize_runtime_environment()
    assert (env.platform, env.shell, env.shell_executable) == (platform, shell, executable)
    assert candidates == ["powershell" if platform == "windows" else executable]
    assert all(os.environ[k] == v for k, v in env.variables().items())
    assert runtime.get_runtime_environment() is env


def test_termux_detection(monkeypatch):
    monkeypatch.setattr(runtime.os, "name", "posix")
    monkeypatch.setenv("TERMUX_VERSION", "0.118.3")
    assert runtime._detect_platform() == "termux"


def test_missing_shell_is_an_explicit_startup_error(monkeypatch):
    monkeypatch.setattr(runtime, "_detect_platform", lambda: "linux")
    monkeypatch.setenv("SHELL", "/missing/bash")
    monkeypatch.setattr(runtime.shutil, "which", lambda candidate: None)
    with pytest.raises(RuntimeError, match="Execution shell is unavailable"):
        runtime.initialize_runtime_environment()


def test_unsupported_shell_is_not_silently_replaced(monkeypatch):
    monkeypatch.setattr(runtime, "_detect_platform", lambda: "linux")
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    monkeypatch.setattr(runtime.shutil, "which", lambda candidate: candidate)
    with pytest.raises(RuntimeError, match="Unsupported POSIX execution shell"):
        runtime.get_runtime_environment()


def test_startup_variables_are_inherited_by_child():
    # Isolate startup mutations from the test runner's environment.
    script = (
        "from src.project_process_environment import apply_project_process_environment; "
        "import subprocess,sys; apply_project_process_environment({}); "
        "subprocess.run([sys.executable,'-c',"
        "'import os,json; print(json.dumps({k:v for k,v in os.environ.items() "
        "if k.startswith(\"AGENTPARK_SHELL\") or k==\"AGENTPARK_PLATFORM\"}))'],check=True)"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    values = json.loads(result.stdout)
    actual = runtime.get_runtime_environment()
    assert values["AGENTPARK_PLATFORM"] == actual.platform
    assert values["AGENTPARK_SHELL"] == actual.shell
    assert values["AGENTPARK_SHELL_EXECUTABLE"] == actual.shell_executable
