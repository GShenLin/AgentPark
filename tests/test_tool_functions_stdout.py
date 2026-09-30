import json
import subprocess
from types import SimpleNamespace

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


def test_file_tools_resolve_relative_paths_from_agent_working_path(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    agent = SimpleNamespace(_agentpark_working_path=str(work))

    write_result = json.loads(write_file("nested/demo.txt", "hello", agent=agent))
    read_result = json.loads(read_file("nested/demo.txt", agent=agent))

    assert write_result["status"] == "success"
    assert write_result["file_path"] == str(work / "nested" / "demo.txt")
    assert read_result["status"] == "success"
    assert read_result["file_path"] == str(work / "nested" / "demo.txt")
    assert read_result["content"] == "hello"


def test_read_file_uses_bounded_output_and_returns_pagination_hint(tmp_path):
    target = tmp_path / "large.txt"
    target.write_text("".join(f"line-{index} {'x' * 100}\n" for index in range(300)), encoding="utf-8")

    raw = read_file(str(target))
    result = json.loads(raw)

    assert result["status"] == "success"
    assert result["output_truncated"] is True
    assert result["output_char_limit"] == 20000
    assert result["next_start_line"] > 1
    assert len(raw) < 20000


def test_read_file_missing_path_suggests_exact_basename_search(tmp_path):
    result = json.loads(read_file(str(tmp_path / "DesktopWorkspace.vue")))

    assert result["status"] == "error"
    assert "**/DesktopWorkspace.vue" in result["next_action"]


def test_read_file_respects_agent_tool_submission_budget(tmp_path):
    target = tmp_path / "large.txt"
    target.write_text(("quoted \\\" content\n" * 1000), encoding="utf-8")
    agent = SimpleNamespace(config={"toolResultSubmissionMaxChars": 4000})

    raw = read_file(str(target), agent=agent)
    result = json.loads(raw)

    assert result["output_truncated"] is True
    assert result["output_char_limit"] == 3600
    assert len(raw) <= 3600


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
