import json
from types import SimpleNamespace

import functions.rg_tools as rg_tools
import functions.system_tools as system_tools


def test_rg_tools_normalize_and_match_globs():
    include = rg_tools.normalize_globs(["*.py", "", "src/**", "*.py"])
    exclude = rg_tools.normalize_globs(["build/**"])

    assert include == ["*.py", "src/**"]
    assert rg_tools.path_allowed("src/a.py", include, exclude) is True
    assert rg_tools.path_allowed("docs/readme.md", include, exclude) is False
    assert rg_tools.path_allowed("build/a.py", include, exclude) is False


def test_parse_rg_line_requires_line_number():
    assert rg_tools.parse_rg_line("src/a.py:12:needle value") == ("src/a.py", 12, "needle value")
    assert rg_tools.parse_rg_line("src/a.py:not-a-number:needle value") is None
    assert rg_tools.parse_rg_line("plain text") is None


def test_rg_search_text_fallback_without_rg(monkeypatch, tmp_path):
    monkeypatch.setattr(rg_tools.shutil, "which", lambda _name: None)

    src = tmp_path / "src"
    src.mkdir()
    file_a = src / "a.py"
    file_b = src / "b.py"
    file_a.write_text("hello world\nneedle value\n", encoding="utf-8")
    file_b.write_text("something else\n", encoding="utf-8")

    raw = rg_tools.rg_search_text(
        query="needle",
        project_root=str(tmp_path),
        include_globs=["*.py"],
        max_results=10,
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert payload["engine"] == "python"
    assert payload["query"] == "needle"
    matches = payload.get("matches") or []
    assert len(matches) == 1
    assert matches[0]["relative_path"].replace("\\", "/") == "src/a.py"
    assert matches[0]["line"] == 2


def test_rg_list_files_fallback_without_rg(monkeypatch, tmp_path):
    monkeypatch.setattr(rg_tools.shutil, "which", lambda _name: None)

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    (tmp_path / "src" / "b.txt").write_text("b\n", encoding="utf-8")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "bundle.js").write_text("bundle\n", encoding="utf-8")

    raw = rg_tools.rg_list_files(
        project_root=str(tmp_path),
        include_globs=["*.py", "*.txt"],
        exclude_globs=["dist/**"],
        max_results=20,
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert payload["engine"] == "python"
    files = {item["relative_path"].replace("\\", "/") for item in payload.get("files") or []}
    assert "src/a.py" in files
    assert "src/b.txt" in files
    assert "dist/bundle.js" not in files


def test_rg_list_files_runs_globs_from_explicit_project_root(monkeypatch, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    target = src / "a.py"
    target.write_text("print('a')\n", encoding="utf-8")
    captured = {}

    def fake_run(cmd, on_line, timeout_sec, cancel_source=None, *, cwd=None):
        captured.update({"cmd": cmd, "cwd": cwd})
        on_line("src/a.py")
        return {
            "ok": True,
            "timed_out": False,
            "stopped_early": False,
            "stderr": "",
            "return_code": 0,
            "had_output": True,
        }

    monkeypatch.setattr(rg_tools.shutil, "which", lambda _name: "rg")
    monkeypatch.setattr(rg_tools, "run_rg_stream_lines", fake_run)

    payload = json.loads(
        rg_tools.rg_list_files(
            project_root=str(tmp_path),
            include_globs=["src/*.py"],
            max_results=10,
        )
    )

    assert captured["cwd"] == str(tmp_path)
    assert captured["cmd"][-1] == "."
    assert payload["files"][0]["file_path"] == str(target)


def test_rg_search_runs_globs_from_explicit_project_root(monkeypatch, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    target = src / "a.py"
    target.write_text("needle\n", encoding="utf-8")
    captured = {}

    def fake_run(cmd, on_line, timeout_sec, cancel_source=None, *, cwd=None):
        captured.update({"cmd": cmd, "cwd": cwd})
        on_line("src/a.py:1:needle")
        return {
            "ok": True,
            "timed_out": False,
            "stopped_early": False,
            "stderr": "",
            "return_code": 0,
            "had_output": True,
        }

    monkeypatch.setattr(rg_tools.shutil, "which", lambda _name: "rg")
    monkeypatch.setattr(rg_tools, "run_rg_stream_lines", fake_run)

    payload = json.loads(
        rg_tools.rg_search_text(
            query="needle",
            project_root=str(tmp_path),
            include_globs=["src/*.py"],
            max_results=10,
        )
    )

    assert captured["cwd"] == str(tmp_path)
    assert captured["cmd"][-2:] == ["needle", "."]
    assert payload["matches"][0]["file_path"] == str(target)


def test_rg_subprocess_timeout_returns_matches_collected_before_deadline(monkeypatch, tmp_path):
    target = tmp_path / "a.py"
    target.write_text("needle\n", encoding="utf-8")

    def fake_run(cmd, on_line, timeout_sec, cancel_source=None, *, cwd=None):
        assert timeout_sec == rg_tools.RG_TIMEOUT_SEC
        on_line("a.py:1:needle")
        return {
            "ok": True,
            "timed_out": True,
            "stopped_early": False,
            "stderr": "",
            "return_code": None,
            "had_output": True,
        }

    monkeypatch.setattr(rg_tools.shutil, "which", lambda _name: "rg")
    monkeypatch.setattr(rg_tools, "run_rg_stream_lines", fake_run)

    payload = json.loads(rg_tools.rg_search_text(
        query="needle",
        project_root=str(tmp_path),
        include_globs=["*.py"],
    ))

    assert payload["status"] == "success"
    assert payload["timed_out"] is True
    assert payload["truncated"] is True
    assert payload["truncation_reason"] == "timeout"
    assert payload["matches"][0]["match"] == "needle"


def test_python_fallback_timeout_returns_matches_collected_before_deadline(monkeypatch, tmp_path):
    target = tmp_path / "a.py"
    target.write_text("needle\nsecond line\n", encoding="utf-8")
    checks = iter([False, False, True])

    monkeypatch.setattr(rg_tools.shutil, "which", lambda _name: None)
    monkeypatch.setattr(rg_tools, "deadline_expired", lambda _deadline: next(checks, True))

    payload = json.loads(rg_tools.rg_search_text(
        query="needle",
        project_root=str(tmp_path),
        include_globs=["*.py"],
    ))

    assert payload["status"] == "success"
    assert payload["engine"] == "python"
    assert payload["timed_out"] is True
    assert payload["truncated"] is True
    assert payload["truncation_reason"] == "timeout"
    assert payload["matches"][0]["match"] == "needle"


def test_python_file_list_timeout_returns_files_collected_before_deadline(monkeypatch, tmp_path):
    (tmp_path / "a.py").write_text("a\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("b\n", encoding="utf-8")
    checks = iter([False, True])

    monkeypatch.setattr(rg_tools.shutil, "which", lambda _name: None)
    monkeypatch.setattr(rg_tools, "deadline_expired", lambda _deadline: next(checks, True))

    payload = json.loads(rg_tools.rg_list_files(
        project_root=str(tmp_path),
        include_globs=["*.py"],
    ))

    assert payload["status"] == "success"
    assert payload["engine"] == "python"
    assert payload["timed_out"] is True
    assert payload["truncation_reason"] == "timeout"
    assert [item["relative_path"] for item in payload["files"]] == ["a.py"]


def test_rg_list_files_blocks_broad_inventory_scan(tmp_path):
    raw = rg_tools.rg_list_files(
        project_root=str(tmp_path),
        include_globs=["**/*"],
        max_results=20000,
    )
    payload = json.loads(raw)

    assert payload["status"] == "blocked"
    assert payload["retryable"] is False
    assert payload["policy"] == "rg_list_files_broad_scan_guard"
    assert "whole-project inventory" in payload["reason"]
    assert "Source/**/*.cpp" in payload["next_query_suggestions"]


def test_rg_list_files_blocks_missing_include_globs(tmp_path):
    raw = rg_tools.rg_list_files(project_root=str(tmp_path), max_results=20000)
    payload = json.loads(raw)

    assert payload["status"] == "blocked"
    assert payload["retryable"] is False
    assert payload["include_globs"] == []


def test_rg_search_text_truncates_by_output_char_budget(monkeypatch, tmp_path):
    monkeypatch.setattr(rg_tools.shutil, "which", lambda _name: None)
    monkeypatch.setattr(rg_tools, "RG_SEARCH_OUTPUT_CHAR_LIMIT", 1800)

    src = tmp_path / "src"
    src.mkdir()
    for index in range(20):
        (src / f"file_{index}.txt").write_text(
            f"needle {'x' * 300}\n",
            encoding="utf-8",
        )

    raw = rg_tools.rg_search_text(
        query="needle",
        project_root=str(tmp_path),
        include_globs=["*.txt"],
        max_results=100,
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert payload["truncated"] is True
    assert payload["truncation_reason"] == "output_char_limit"
    assert payload["matches_returned"] < 20
    assert payload["output_char_limit"] == 1800
    assert len(raw) <= 1800


def test_rg_search_text_defaults_to_agent_working_path(monkeypatch, tmp_path):
    monkeypatch.setattr(rg_tools.shutil, "which", lambda _name: None)

    work = tmp_path / "work"
    other = tmp_path / "other"
    work.mkdir()
    other.mkdir()
    (work / "target.txt").write_text("needle in work\n", encoding="utf-8")
    (other / "target.txt").write_text("needle elsewhere\n", encoding="utf-8")

    raw = rg_tools.rg_search_text(
        query="needle",
        include_globs=["*.txt"],
        agent=SimpleNamespace(_agentpark_working_path=str(work)),
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert payload["project_root"] == str(work)
    assert [item["relative_path"] for item in payload["matches"]] == ["target.txt"]


def test_rg_list_files_defaults_to_agent_working_path(monkeypatch, tmp_path):
    monkeypatch.setattr(rg_tools.shutil, "which", lambda _name: None)

    work = tmp_path / "work"
    work.mkdir()
    (work / "target.py").write_text("print('ok')\n", encoding="utf-8")

    raw = rg_tools.rg_list_files(
        include_globs=["*.py"],
        agent=SimpleNamespace(config={"working_path": str(work)}),
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert payload["project_root"] == str(work)
    assert [item["relative_path"] for item in payload["files"]] == ["target.py"]


def test_rg_relative_project_root_resolves_from_agent_working_path(monkeypatch, tmp_path):
    monkeypatch.setattr(rg_tools.shutil, "which", lambda _name: None)

    work = tmp_path / "work"
    work.mkdir()
    (work / "target.py").write_text("print('ok')\n", encoding="utf-8")

    raw = rg_tools.rg_list_files(
        project_root=".",
        include_globs=["*.py"],
        agent=SimpleNamespace(_agentpark_working_path=str(work)),
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert payload["project_root"] == str(work)
    assert [item["relative_path"] for item in payload["files"]] == ["target.py"]


def test_rg_results_respect_agent_tool_submission_budget(monkeypatch, tmp_path):
    monkeypatch.setattr(rg_tools.shutil, "which", lambda _name: None)
    for index in range(30):
        (tmp_path / f"long_target_{index}.txt").write_text(
            "needle " + ("x" * 200),
            encoding="utf-8",
        )
    agent = SimpleNamespace(config={"toolResultSubmissionMaxChars": 4000})

    raw = rg_tools.rg_search_text(
        query="needle",
        project_root=str(tmp_path),
        include_globs=["*.txt"],
        max_results=100,
        agent=agent,
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert payload["truncated"] is True
    assert payload["output_char_limit"] == 3600
    assert len(raw) <= 3600


def test_system_tools_exports_rg_tools():
    assert "rg_search_text" in system_tools.__all__
    assert "rg_search_text_declaration" in system_tools.__all__
    assert "rg_list_files" in system_tools.__all__
    assert "rg_list_files_declaration" in system_tools.__all__
    assert callable(system_tools.rg_search_text)
    assert callable(system_tools.rg_list_files)
    assert "find_files_declaration" not in system_tools.__all__
    assert "search_text_in_files_declaration" not in system_tools.__all__
    assert "find_class_definition_declaration" not in system_tools.__all__
    assert not hasattr(system_tools, "find_files_declaration")
    assert not hasattr(system_tools, "search_text_in_files_declaration")
    assert not hasattr(system_tools, "find_class_definition_declaration")


def test_rg_tools_use_cooperative_timeout_longer_than_internal_scan_timeout():
    for tool in (rg_tools.rg_search_text, rg_tools.rg_list_files):
        assert tool.tool_cooperative_cancellation is True
        assert tool.tool_timeout_seconds > rg_tools.RG_TIMEOUT_SEC


def test_system_tools_do_not_export_skill_scoped_computer_use_tools():
    assert "list_windows" not in system_tools.__all__
    assert "get_window_state" not in system_tools.__all__
    assert "click" not in system_tools.__all__
    assert "type_text" not in system_tools.__all__
