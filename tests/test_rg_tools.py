import json

import functions.rg_tools as rg_tools
import functions.system_tools as system_tools


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
