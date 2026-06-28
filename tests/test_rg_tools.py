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


def test_project_file_stats_skips_generated_dirs_and_counts_top_file_lines(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "small.py").write_text("print('a')\n", encoding="utf-8")
    (tmp_path / "src" / "large.py").write_text("one\ntwo\nthree", encoding="utf-8")
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "bundle.js").write_text("bundle\n", encoding="utf-8")

    raw = rg_tools.project_file_stats(
        project_root=str(tmp_path),
        include_globs=["*.py", "*.js"],
        top_n=1,
        include_line_counts=True,
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert payload["scanned_files"] == 2
    assert payload["by_extension"][".py"]["files"] == 2
    assert ".js" not in payload["by_extension"]
    assert payload["line_counts_scope"] == "top_files_by_size"
    assert payload["top_files_by_size"][0]["relative_path"].replace("\\", "/") == "src/large.py"
    assert payload["top_files_by_size"][0]["line_count"] == 3


def test_system_tools_exports_rg_tools():
    assert "rg_search_text" in system_tools.__all__
    assert "rg_search_text_declaration" in system_tools.__all__
    assert "rg_list_files" in system_tools.__all__
    assert "rg_list_files_declaration" in system_tools.__all__
    assert "project_file_stats" in system_tools.__all__
    assert "project_file_stats_declaration" in system_tools.__all__
    assert callable(system_tools.rg_search_text)
    assert callable(system_tools.rg_list_files)
    assert callable(system_tools.project_file_stats)
    assert "find_files_declaration" not in system_tools.__all__
    assert "search_text_in_files_declaration" not in system_tools.__all__
    assert "find_class_definition_declaration" not in system_tools.__all__
    assert not hasattr(system_tools, "find_files_declaration")
    assert not hasattr(system_tools, "search_text_in_files_declaration")
    assert not hasattr(system_tools, "find_class_definition_declaration")
