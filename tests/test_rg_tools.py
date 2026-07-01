import json

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
