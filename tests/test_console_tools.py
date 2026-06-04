import json
import subprocess

from functions.console_tools import execute_console_command


def test_execute_console_command_decodes_powershell_stdout_as_utf8(monkeypatch, capsys):
    class _Completed:
        stdout = "回显输入\n".encode("utf-8")
        stderr = b""
        returncode = 0

    def _fake_run(*args, **kwargs):
        return _Completed()

    monkeypatch.setattr(subprocess, "run", _fake_run)

    result = json.loads(execute_console_command("powershell.exe -NoProfile -Command \"'回显输入'\""))

    assert result["status"] == "success"
    assert result["stdout"] == "回显输入\n"
    assert capsys.readouterr().out == ""


def test_execute_console_command_falls_back_to_locale_encoding(monkeypatch):
    class _Completed:
        stdout = "中文\n".encode("cp936")
        stderr = b""
        returncode = 0

    def _fake_run(*args, **kwargs):
        return _Completed()

    monkeypatch.setattr(subprocess, "run", _fake_run)

    result = json.loads(execute_console_command("cmd.exe /c echo 中文"))

    assert result["status"] == "success"
    assert result["stdout"] == "中文\n"


def test_execute_console_command_timeout_uses_same_decoder(monkeypatch, capsys):
    def _fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=kwargs.get("args", args[0] if args else ""),
            timeout=15,
            output="回显输入\n".encode("utf-8"),
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    result = json.loads(execute_console_command("powershell.exe -NoProfile -Command \"'回显输入'\""))

    assert result["status"] == "timeout"
    assert result["stdout"] == "回显输入\n"
    assert capsys.readouterr().out == ""
