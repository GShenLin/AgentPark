import json
import subprocess

from functions.curl_tools import execute_curl_command
from functions.file_read_tools import read_file
from functions.file_write_tools import write_file


def test_file_tools_do_not_emit_progress_to_stdout(tmp_path, capsys):
    target = tmp_path / "demo.txt"

    write_result = json.loads(write_file(str(target), "hello"))
    read_result = json.loads(read_file(str(target)))

    assert write_result["status"] == "success"
    assert read_result["status"] == "success"
    assert read_result["content"] == "hello"
    assert capsys.readouterr().out == ""


def test_curl_tool_does_not_emit_progress_to_stdout(monkeypatch, capsys):
    class _Completed:
        stdout = b"ok"
        stderr = b""
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: _Completed())

    result = json.loads(execute_curl_command("https://example.com"))

    assert result["status"] == "success"
    assert result["stdout"] == "ok"
    assert capsys.readouterr().out == ""


def test_curl_tool_html_output_remains_json_string(monkeypatch):
    class _Completed:
        stdout = b'<!doctype html><html lang="en"></html>'
        stderr = b""
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: _Completed())

    raw = execute_curl_command("https://example.com")
    result = json.loads(raw)

    assert isinstance(raw, str)
    assert result["status"] == "success"
    assert result["stdout"].startswith("<!doctype html>")
