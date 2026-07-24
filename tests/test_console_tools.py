import json
import io
import shutil
import subprocess
import sys

import pytest

import functions.console_tools as console_tools
import functions.console_process_runtime as console_process_runtime
from functions.console_tools import execute_console_command


class _FakePopen:
    def __init__(self, *, stdout=b"", stderr=b"", returncode=0, running=False, pid=0):
        self._stdout = stdout
        self._stderr = stderr
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = returncode
        self._running = running
        self.pid = pid
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


@pytest.mark.skipif(shutil.which("powershell") is None, reason="PowerShell is unavailable")
def test_execute_console_command_propagates_native_process_exit_code():
    result = json.loads(
        execute_console_command(
            f'& "{sys.executable}" -c "import sys; sys.exit(7)"',
            timeout_seconds=10,
        )
    )

    assert result["status"] == "error"
    assert result["returncode"] == 7


def test_execute_console_command_rejects_non_utf8_output_without_replacement(monkeypatch):
    def _fake_popen(*args, **kwargs):
        return _FakePopen(stdout="中文\n".encode("cp936"), stderr=b"", returncode=0)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = json.loads(execute_console_command("cmd.exe /c echo 中文"))

    assert result["status"] == "exception"
    assert "violated the UTF-8 console protocol" in result["error"]
    assert "�" not in result["error"]


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


def test_execute_console_command_timeout_kills_windows_process_tree(monkeypatch):
    fake_proc = _FakePopen(stdout=b"", stderr=b"", running=True, pid=4242)
    run_calls = []

    class _Completed:
        def __init__(self, stdout="", returncode=0):
            self.stdout = stdout
            self.stderr = ""
            self.returncode = returncode

    def _fake_popen(*args, **kwargs):
        return fake_proc

    def _fake_run(args, **kwargs):
        run_calls.append(list(args))
        if args[:3] == ["powershell", "-NoProfile", "-Command"]:
            return _Completed(stdout="5252\n")
        if args and args[0] == "taskkill":
            return _Completed()
        raise AssertionError(f"unexpected subprocess.run call: {args}")

    times = iter([0, 2])
    monkeypatch.setattr(subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setattr(console_process_runtime.os, "name", "nt")
    monkeypatch.setattr(console_tools.time, "monotonic", lambda: next(times, 2))
    monkeypatch.setattr(console_tools.time, "sleep", lambda _seconds: None)

    result = json.loads(execute_console_command("powershell -NoProfile -Command \"Start-Sleep 60\"", timeout_seconds=1))

    assert result["status"] == "timeout"
    assert ["taskkill", "/PID", "4242", "/T", "/F"] in run_calls
    assert ["taskkill", "/PID", "5252", "/T", "/F"] in run_calls


def test_execute_console_command_blocks_interactive_npx_skills_find(monkeypatch):
    def _fake_popen(*args, **kwargs):
        raise AssertionError("blocked command should not start a process")

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = json.loads(execute_console_command("npx skills find lark"))

    assert result["status"] == "blocked"
    assert "npx --yes skills find" in result["hint"]


def test_execute_console_command_runs_commands_through_powershell_without_shell_true(monkeypatch):
    popen_args = []
    popen_kwargs = {}

    def _fake_popen(*args, **kwargs):
        popen_args.extend(args)
        popen_kwargs.update(kwargs)
        return _FakePopen(stdout=b"Path\n----\nD:\\Project\\AgentPark\n", stderr=b"", returncode=0)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = json.loads(execute_console_command("pwd"))

    assert result["status"] == "success"
    assert popen_args[0][:3] == ["powershell", "-NoProfile", "-Command"]
    powershell_script = popen_args[0][3]
    assert "[Console]::InputEncoding = $__AgentParkUtf8" in powershell_script
    assert "[Console]::OutputEncoding = $__AgentParkUtf8" in powershell_script
    assert "$OutputEncoding = $__AgentParkUtf8" in powershell_script
    assert "& {\npwd\nif (-not $?)" in powershell_script
    assert "exit $LASTEXITCODE" in powershell_script
    assert "shell" not in popen_kwargs


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
    assert "rg_list_files" in result["hint"]


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
    assert "rg_list_files" in result["hint"]


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


def test_execute_console_command_fits_serialized_result_to_provider_submission_limit(
    monkeypatch,
):
    stderr = ("ROOT_CAUSE\n" + ("E   repeated traceback\n" * 20_000) + "LAST_ERROR\n").encode()
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *args, **kwargs: _FakePopen(stderr=stderr, returncode=1),
    )

    serialized = execute_console_command(
        "python -m pytest -q tests/test_contract.py",
        agent=_Agent(
            {
                "consoleCommandOutputMaxChars": 131072,
                "toolResultSubmissionMaxChars": 50000,
            }
        ),
    )
    result = json.loads(serialized)

    assert len(serialized) <= 50000
    assert result["status"] == "error"
    assert result["stderr"].startswith("ROOT_CAUSE")
    assert result["stderr"].endswith("LAST_ERROR\n")
    assert result["output_max_chars_per_stream"] == 131072
    assert result["output_effective_max_chars_per_stream"] < 131072
    assert result["output_submission_budget"] == {
        "applied": True,
        "configured_submission_max_chars": 50000,
        "configured_output_max_chars_per_stream": 131072,
        "effective_output_max_chars_per_stream": result[
            "output_effective_max_chars_per_stream"
        ],
        "strategy": "serialized_payload_binary_search",
    }


def test_execute_console_command_rejects_invalid_provider_submission_limit(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *args, **kwargs: _FakePopen(stdout=b"ok"),
    )

    result = json.loads(
        execute_console_command(
            "cmd.exe /c echo ok",
            agent=_Agent({"toolResultSubmissionMaxChars": "50000"}),
        )
    )

    assert result["status"] == "exception"
    assert result["error"] == (
        "agent.config.toolResultSubmissionMaxChars must be a positive integer"
    )


def test_execute_console_command_uses_agent_working_path_as_cwd(monkeypatch, tmp_path):
    popen_kwargs = {}

    def _fake_popen(*args, **kwargs):
        popen_kwargs.update(kwargs)
        return _FakePopen(stdout=b"ok\n", stderr=b"", returncode=0)

    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    result = json.loads(
        execute_console_command(
            "cmd.exe /c echo ok",
            agent=_Agent({"working_path": str(tmp_path)}),
        )
    )

    assert result["status"] == "success"
    assert result["cwd"] == str(tmp_path)
    assert popen_kwargs["cwd"] == str(tmp_path)


def test_execute_console_command_errors_when_agent_working_path_is_missing(tmp_path):
    missing = tmp_path / "missing"

    result = json.loads(
        execute_console_command(
            "cmd.exe /c echo ok",
            agent=_Agent({"working_path": str(missing)}),
        )
    )

    assert result["status"] == "exception"
    assert "WorkingPath directory does not exist" in result["error"]


def test_execute_console_command_drains_large_stdout_without_pipe_deadlock():
    command = f'& "{sys.executable}" -c "import sys; sys.stdout.write(\'x\' * 200000)"'

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
    assert result["stderr"] == "abERR"
    assert result["stderr_truncated"] is True
    assert result["stderr_original_chars"] == 13
    assert result["stderr_returned_chars"] == 5
    assert result["output_truncation"]["streams"][0]["stream"] == "stderr"
    assert result["output_truncation"]["streams"][0]["strategy"] == "head_tail"


def test_execute_console_command_timeout_preserves_failure_head_and_tail(monkeypatch):
    stderr = b"ROOT_CAUSE:" + (b"x" * 100) + b":LAST_ERROR"
    proc = _FakePopen(stdout=b"", stderr=stderr, running=True)
    times = iter([0, 2])
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(console_tools.time, "monotonic", lambda: next(times, 2))
    monkeypatch.setattr(console_tools.time, "sleep", lambda _seconds: None)

    result = json.loads(
        execute_console_command(
            "cmd.exe /c hangs",
            timeout_seconds=1,
            agent=_Agent({"consoleCommandOutputMaxChars": 80}),
        )
    )

    assert result["status"] == "timeout"
    assert result["stderr"].startswith("ROOT_CA")
    assert result["stderr"].endswith(":LAST_ERROR")
    assert result["output_truncation"]["streams"][0]["strategy"] == "head_tail"


def test_execute_console_command_pytest_no_progress_watchdog(monkeypatch):
    proc = _FakePopen(
        stdout=b"collecting tests\n",
        stderr=b"E   registration request.token must be a string\n" * 100,
        running=True,
    )
    times = iter([0, 61])
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: proc)
    monkeypatch.setattr(console_tools.time, "monotonic", lambda: next(times, 61))
    monkeypatch.setattr(console_tools.time, "sleep", lambda _seconds: None)

    result = json.loads(
        execute_console_command(
            "python -m pytest -q tests/test_contracts.py",
            timeout_seconds=300,
            progress_timeout_seconds=60,
        )
    )

    assert result["status"] == "no_progress_timeout"
    assert result["progress_watchdog"] == {
        "kind": "pytest",
        "timeout_seconds": 60.0,
        "progress_events": 0,
        "elapsed_seconds": 61.0,
        "seconds_since_progress": 61.0,
    }
    assert "stderr activity does not reset it" in result["error"]


def test_execute_console_command_rejects_zero_exit_when_pytest_reports_failures(monkeypatch):
    proc = _FakePopen(
        stdout=(
            b"................................FFF\n"
            b"3 failed, 59 passed, 1 skipped in 2.10s\n"
        ),
        returncode=0,
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: proc)

    result = json.loads(
        execute_console_command(
            "python -m pytest -q tests/test_contracts.py",
            timeout_seconds=300,
            progress_timeout_seconds=60,
        )
    )

    assert result["status"] == "error"
    assert result["detected_completion"] == {
        "kind": "pytest",
        "completed": True,
        "failed_tests": 3,
    }
    assert result["error"] == (
        "Pytest reported 3 failed/error tests despite a zero process return code."
    )


def test_execute_console_command_preserves_zero_exit_for_passing_pytest(monkeypatch):
    proc = _FakePopen(
        stdout=b"59 passed, 1 skipped in 2.10s\n",
        returncode=0,
    )
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: proc)

    result = json.loads(
        execute_console_command(
            "python -m pytest -q tests/test_contracts.py",
            timeout_seconds=300,
            progress_timeout_seconds=60,
        )
    )

    assert result["status"] == "success"
    assert result["detected_completion"] == {
        "kind": "pytest",
        "completed": True,
        "failed_tests": 0,
    }


def test_execute_console_command_rejects_progress_watchdog_for_non_pytest(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("invalid contract must fail before spawning"),
    )

    result = json.loads(
        execute_console_command(
            "python -m compileall src",
            timeout_seconds=300,
            progress_timeout_seconds=60,
        )
    )

    assert result["status"] == "exception"
    assert result["error"] == (
        "progress_timeout_seconds is supported only for pytest test runs"
    )


def test_execute_console_command_rejects_redundant_progress_timeout(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("invalid contract must fail before spawning"),
    )

    result = json.loads(
        execute_console_command(
            "python -m pytest tests/test_contracts.py",
            timeout_seconds=300,
            progress_timeout_seconds=300,
        )
    )

    assert result["status"] == "exception"
    assert result["error"] == (
        "progress_timeout_seconds must be less than the command timeout"
    )


def test_execute_console_command_declaration_allows_explicit_null_watchdog():
    schema = console_tools.execute_console_command_declaration["function"]["parameters"]

    assert schema["properties"]["progress_timeout_seconds"]["type"] == [
        "number",
        "null",
    ]


def test_execute_console_command_declaration_explains_expected_native_nonzero_exit():
    description = console_tools.execute_console_command_declaration["function"]["description"]

    assert "Native non-zero exit codes are propagated" in description
    assert "rg exit 1 for no matches" in description
    assert "$LASTEXITCODE" in description


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
