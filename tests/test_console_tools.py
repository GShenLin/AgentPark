import json
import io
import subprocess
import sys

import pytest

import functions.console_tools as console_tools
from functions.console_tools import execute_console_command


class _FakePopen:
    def __init__(self, *, stdout=b"", stderr=b"", returncode=0, running=False):
        self._stdout = stdout
        self._stderr = stderr
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode
        self._running = running
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self._running and not self.terminated and not self.killed else self.returncode

    def communicate(self, timeout=None):
        return self._stdout, self._stderr

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


def test_execute_console_command_decodes_powershell_stdout_as_utf8(monkeypatch, capsys):
    def _fake_popen(*args, **kwargs):
        return _FakePopen(stdout="回显输入\n".encode("utf-8"), stderr=b"", returncode=0)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = json.loads(execute_console_command("powershell.exe -NoProfile -Command \"'回显输入'\""))

    assert result["status"] == "success"
    assert result["stdout"] == "回显输入\n"
    assert capsys.readouterr().out == ""


def test_execute_console_command_falls_back_to_locale_encoding(monkeypatch):
    def _fake_popen(*args, **kwargs):
        return _FakePopen(stdout="中文\n".encode("cp936"), stderr=b"", returncode=0)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(console_tools.locale, "getpreferredencoding", lambda *_args: "cp936")

    result = json.loads(execute_console_command("cmd.exe /c echo 中文"))

    assert result["status"] == "success"
    assert result["stdout"] == "中文\n"


def test_execute_console_command_timeout_uses_same_decoder(monkeypatch, capsys):
    def _fake_popen(*args, **kwargs):
        return _FakePopen(stdout="回显输入\n".encode("utf-8"), stderr=b"", running=True)

    times = iter([0, 2])
    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(console_tools.time, "monotonic", lambda: next(times, 2))
    monkeypatch.setattr(console_tools.time, "sleep", lambda _seconds: None)

    result = json.loads(execute_console_command("powershell.exe -NoProfile -Command \"'回显输入'\"", timeout_seconds=1))

    assert result["status"] == "timeout"
    assert result["stdout"] == "回显输入\n"
    assert capsys.readouterr().out == ""


def test_execute_console_command_blocks_interactive_npx_skills_find(monkeypatch):
    def _fake_popen(*args, **kwargs):
        raise AssertionError("blocked command should not start a process")

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = json.loads(execute_console_command("npx skills find lark"))

    assert result["status"] == "blocked"
    assert "npx --yes skills find" in result["hint"]


def test_execute_console_command_blocks_unix_pwd_in_cmd(monkeypatch):
    def _fake_popen(*args, **kwargs):
        raise AssertionError("blocked command should not start a process")

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = json.loads(execute_console_command("pwd && git status --short"))

    assert result["status"] == "blocked"
    assert "'cd'" in result["hint"]


def test_execute_console_command_blocks_high_context_git_diff(monkeypatch):
    def _fake_popen(*args, **kwargs):
        raise AssertionError("blocked command should not start a process")

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = json.loads(execute_console_command("git --no-pager diff --unified=80 -- webui/src/App.vue"))

    assert result["status"] == "blocked"
    assert "--stat" in result["hint"]


def test_execute_console_command_blocks_broad_powershell_line_count(monkeypatch):
    def _fake_popen(*args, **kwargs):
        raise AssertionError("blocked command should not start a process")

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = json.loads(
        execute_console_command(
            "powershell -NoProfile -Command \"Get-ChildItem -Recurse | Get-Content | Measure-Object -Line\""
        )
    )

    assert result["status"] == "blocked"
    assert "project_file_stats" in result["hint"]


def test_execute_console_command_blocks_rg_files_line_count_pipeline(monkeypatch):
    def _fake_popen(*args, **kwargs):
        raise AssertionError("blocked command should not start a process")

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = json.loads(
        execute_console_command(
            "powershell -NoProfile -Command \"rg --files | Get-Content | Measure-Object -Line\""
        )
    )

    assert result["status"] == "blocked"
    assert "project_file_stats" in result["hint"]


def test_execute_console_command_webui_build_timeout_reports_partial_success(monkeypatch):
    def _fake_popen(*args, **kwargs):
        return _FakePopen(stdout=b"vite v5.0.0 building...\nbuilt in 4.21s\n", stderr=b"", running=True)

    times = iter([0, 541])
    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(console_tools.time, "monotonic", lambda: next(times, 541))
    monkeypatch.setattr(console_tools.time, "sleep", lambda _seconds: None)

    result = json.loads(execute_console_command("cd webui && npm run build", timeout_seconds=1))

    assert result["status"] == "partial_success_timeout"
    assert result["detected_completion"]["kind"] == "webui_build"
    assert result["detected_completion"]["completed"] is True
    assert "completed WebUI build" in result["error"]


def test_execute_console_command_pytest_collect_timeout_reports_partial_success(monkeypatch):
    def _fake_popen(*args, **kwargs):
        return _FakePopen(stdout=b"123 tests collected in 3.44s\n", stderr=b"", running=True)

    times = iter([0, 181])
    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(console_tools.time, "monotonic", lambda: next(times, 181))
    monkeypatch.setattr(console_tools.time, "sleep", lambda _seconds: None)

    result = json.loads(execute_console_command("python -m pytest --collect-only -q", timeout_seconds=1))

    assert result["status"] == "partial_success_timeout"
    assert result["detected_completion"]["kind"] == "pytest_collect"
    assert result["detected_completion"]["collected_tests"] == 123


def test_execute_console_command_limits_stdout_to_tail_and_reports_truncation(monkeypatch):
    def _fake_popen(*args, **kwargs):
        return _FakePopen(stdout=b"0123456789TAIL", stderr=b"", returncode=0)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = json.loads(
        execute_console_command(
            "cmd.exe /c echo large",
            agent=_Agent({"consoleCommandOutputMaxChars": 6}),
        )
    )

    assert result["status"] == "success"
    assert result["stdout"] == "89TAIL"
    assert result["stdout_truncated"] is True
    assert result["stdout_original_chars"] == 14
    assert result["stdout_returned_chars"] == 6
    assert result["stderr_truncated"] is False
    assert result["output_truncated"] is True
    assert "tail content" in result["output_truncation_notice"]
    assert result["output_truncation"]["streams"][0]["stream"] == "stdout"


def test_execute_console_command_uses_a_relaxed_default_output_limit(monkeypatch):
    def _fake_popen(*args, **kwargs):
        return _FakePopen(stdout=b"abc", stderr=b"", returncode=0)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = json.loads(execute_console_command("cmd.exe /c echo ok"))

    assert result["output_max_chars_per_stream"] == 131072


def test_execute_console_command_drains_large_stdout_without_pipe_deadlock():
    command = f'"{sys.executable}" -c "import sys; sys.stdout.write(\'x\' * 200000)"'

    result = json.loads(execute_console_command(command, timeout_seconds=10))

    assert result["status"] == "success"
    assert result["stdout_truncated"] is True
    assert result["stdout_original_chars"] == 200000
    assert result["stdout_returned_chars"] == 131072
    assert result["stdout"] == "x" * 131072


def test_execute_console_command_limits_stderr_to_tail_and_reports_truncation(monkeypatch):
    def _fake_popen(*args, **kwargs):
        return _FakePopen(stdout=b"", stderr=b"abcdefghijERR", returncode=1)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = json.loads(
        execute_console_command(
            "cmd.exe /c bad",
            agent=_Agent({"consoleCommand": {"outputMaxChars": 5}}),
        )
    )

    assert result["status"] == "error"
    assert result["stderr"] == "ijERR"
    assert result["stderr_truncated"] is True
    assert result["stderr_original_chars"] == 13
    assert result["stderr_returned_chars"] == 5
    assert result["output_truncation"]["streams"][0]["stream"] == "stderr"


class _Agent:
    def __init__(self, config):
        self.config = config


def test_resolve_command_timeout_prefers_explicit_value(monkeypatch):
    monkeypatch.setattr(console_tools, "load_workspace_settings", lambda: {"consoleCommandTimeoutSec": 300})

    assert console_tools._resolve_command_timeout_seconds("45", _Agent({"consoleCommandTimeoutSec": 90})) == 45


def test_resolve_command_timeout_uses_agent_config_before_workspace(monkeypatch):
    monkeypatch.setattr(console_tools, "load_workspace_settings", lambda: {"consoleCommandTimeoutSec": 300})

    assert console_tools._resolve_command_timeout_seconds(None, _Agent({"consoleCommandTimeoutSec": 90})) == 90


def test_resolve_command_timeout_uses_workspace_console_section(monkeypatch):
    monkeypatch.setattr(console_tools, "load_workspace_settings", lambda: {"consoleCommand": {"timeoutSec": 300}})

    assert console_tools._resolve_command_timeout_seconds(None, _Agent({})) == 300


def test_resolve_command_timeout_rejects_invalid_config(monkeypatch):
    monkeypatch.setattr(console_tools, "load_workspace_settings", lambda: {"consoleCommandTimeoutSec": "soon"})

    with pytest.raises(ValueError, match="config/config.json.consoleCommandTimeoutSec"):
        console_tools._resolve_command_timeout_seconds(None, _Agent({}))
