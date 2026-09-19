import json
import os
import shlex
import signal
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from functions.console_tools import execute_console_command
from functions.console_process_runtime import terminate_process
from src.providers.agent_environment_context import build_agent_environment_context
from src.runtime_environment import get_runtime_environment


@pytest.mark.skipif(os.name == "nt", reason="POSIX execution integration")
def test_posix_utf8_cwd_pipelines_and_environment(tmp_path):
    working = tmp_path / "含空格 workspace"
    working.mkdir()
    agent = SimpleNamespace(_agentpark_working_path=str(working), config={"shell": "powershell"})
    command = (
        'printf "中文\\n" | cat; pwd; '
        'printf "%s\\n" "$AGENTPARK_PLATFORM" "$AGENTPARK_SHELL" "$PYTHONIOENCODING"'
    )
    result = json.loads(execute_console_command(command, agent=agent))
    env = get_runtime_environment()
    assert result["status"] == "success"
    assert result["returncode"] == 0
    assert result["stdout"].splitlines() == ["中文", str(working), env.platform, env.shell, "utf-8"]
    assert result["cwd"] == str(working)
    assert build_agent_environment_context(agent)["shell"] == env.shell


@pytest.mark.skipif(os.name == "nt", reason="POSIX execution integration")
def test_posix_native_failure_preserves_stderr_and_exit_code():
    command = f"{shlex.quote(sys.executable)} -c " + shlex.quote(
        "import sys; print('失败',file=sys.stderr); sys.exit(7)"
    )
    result = json.loads(execute_console_command(command))
    assert result["status"] == "error"
    assert result["returncode"] == 7
    assert result["stderr"] == "失败\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX execution integration")
def test_posix_timeout_kills_descendants_holding_pipes(tmp_path):
    marker = tmp_path / "should-not-exist"
    script = "import time,pathlib; time.sleep(2); pathlib.Path('should-not-exist').write_text('leaked')"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(script)} & wait"
    agent = SimpleNamespace(_agentpark_working_path=str(tmp_path))
    result = json.loads(execute_console_command(command, timeout_seconds=1, agent=agent))
    assert result["status"] == "timeout"
    time.sleep(1.3)
    assert not marker.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
def test_posix_cleanup_kills_group_even_when_shell_has_exited(monkeypatch):
    import functions.console_process_runtime as module
    calls = []
    proc = SimpleNamespace(pid=4242, _agentpark_process_group=True, poll=lambda: 0, wait=lambda **kw: 0)
    monkeypatch.setattr(module.os, "name", "posix")
    monkeypatch.setattr(module.os, "killpg", lambda pid, sig: calls.append((pid, sig)), raising=False)
    terminate_process(proc)
    assert calls == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]


@pytest.mark.skipif(os.name == "nt", reason="POSIX execution integration")
def test_posix_stop_cancels_command_and_children(tmp_path):
    event = threading.Event()
    agent = SimpleNamespace(cancel_event=event, _agentpark_working_path=str(tmp_path))
    script = "import time,pathlib; time.sleep(2); pathlib.Path('leaked').write_text('leaked')"
    command = f"{shlex.quote(sys.executable)} -c {shlex.quote(script)} & wait"
    timer = threading.Timer(0.3, event.set)
    timer.start()
    try:
        result = json.loads(execute_console_command(command, timeout_seconds=10, agent=agent))
    finally:
        timer.cancel()
    assert result["status"] == "stopped"
    time.sleep(2)
    assert not (tmp_path / "leaked").exists()


def test_remote_shell_metadata_keeps_worker_context(tmp_path):
    agent = SimpleNamespace(
        _agentpark_remote_enabled=True,
        _agentpark_shell="powershell",
        _agentpark_working_path=r"C:\remote\project",
        config={},
    )
    context = build_agent_environment_context(agent)
    assert context["shell"] == "powershell"
    assert context["workspace_path"] == r"C:\remote\project"
