import json
import os
from types import SimpleNamespace

import functions.system_tools as patch_tools
import functions.system_tools as system_tools
from src.tool.base_tool import BaseTool


class _DummyAgent:
    def __init__(self):
        self.config = {}


def test_apply_patch_add_update_delete_file(tmp_path):
    file_path = tmp_path / "demo.txt"
    added_path = tmp_path / "added.txt"
    delete_path = tmp_path / "delete.txt"
    delete_path.write_text("remove me\n", encoding="utf-8")

    raw = patch_tools.apply_patch(
        f"""*** Begin Patch
*** Add File: {added_path}
+created
*** Update File: {file_path}
*** End Patch"""
    )
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert "Update File target does not exist" in payload["error"]
    assert not added_path.exists()

    file_path.write_text("hello\nold value\nbye\n", encoding="utf-8")
    raw = patch_tools.apply_patch(
        f"""*** Begin Patch
*** Add File: {added_path}
+created
*** Update File: {file_path}
@@ demo block
 hello
-old value
+new value
 bye
*** Delete File: {delete_path}
*** End Patch"""
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert file_path.read_text(encoding="utf-8") == "hello\nnew value\nbye\n"
    assert added_path.read_text(encoding="utf-8") == "created\n"
    assert not delete_path.exists()
    changes = {item["path"]: item for item in payload["file_changes"]}
    update = changes[str(file_path)]
    assert "hunks" not in update
    assert update["additions"] == 1
    assert update["deletions"] == 1
    assert payload["stats"] == {"files": 3, "additions": 2, "deletions": 2}
    assert payload["diff"]["omitted_from_model"] is True
    assert os.path.isfile(payload["diff"]["structured_diff_path"])
    assert os.path.isfile(payload["diff"]["unified_diff_path"])

    artifact = json.loads(open(payload["diff"]["structured_diff_path"], "r", encoding="utf-8").read())
    artifact_changes = {item["path"]: item for item in artifact["file_changes"]}
    update = artifact_changes[str(file_path)]
    changed_row = next(
        row
        for hunk in update["hunks"]
        for row in hunk["rows"]
        if row.get("before_text") == "old value"
    )
    assert changed_row == {
        "kind": "change",
        "before_line": 2,
        "before_text": "old value",
        "after_line": 2,
        "after_text": "new value",
    }
    assert update["hunks"][0]["context_lines"] == 5
    unified = open(payload["diff"]["unified_diff_path"], "r", encoding="utf-8").read()
    assert f"--- {file_path}" in unified
    assert f"+++ {file_path}" in unified
    assert "-old value" in unified
    assert "+new value" in unified


def test_apply_patch_full_return_mode_keeps_small_diff_in_payload(tmp_path):
    file_path = tmp_path / "demo.txt"
    file_path.write_text("old\n", encoding="utf-8")

    raw = patch_tools.apply_patch(
        f"""*** Begin Patch
*** Update File: {file_path}
@@
-old
+new
*** End Patch""",
        return_mode="full",
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert payload["diff"]["omitted_from_model"] is False
    assert payload["file_changes"][0]["hunks"][0]["rows"][0]["before_text"] == "old"


def test_apply_patch_move_file(tmp_path):
    source_path = tmp_path / "source.txt"
    target_path = tmp_path / "target.txt"
    source_path.write_text("alpha\nbeta\n", encoding="utf-8")

    raw = patch_tools.apply_patch(
        f"""*** Begin Patch
*** Update File: {source_path}
*** Move to: {target_path}
@@
 alpha
-beta
+gamma
*** End Patch"""
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert not source_path.exists()
    assert target_path.read_text(encoding="utf-8") == "alpha\ngamma\n"


def test_apply_patch_rejects_missing_context(tmp_path):
    file_path = tmp_path / "demo.txt"
    file_path.write_text("actual\n", encoding="utf-8")

    raw = patch_tools.apply_patch(
        f"""*** Begin Patch
*** Update File: {file_path}
@@
-expected
+changed
*** End Patch"""
    )
    payload = json.loads(raw)

    assert payload["status"] == "error"
    assert "Could not locate update hunk" in payload["error"]
    assert file_path.read_text(encoding="utf-8") == "actual\n"


def test_apply_patch_resolves_relative_paths_from_agent_working_path(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "source.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    agent = SimpleNamespace(_agentpark_working_path=str(work))

    raw = patch_tools.apply_patch(
        """*** Begin Patch
*** Add File: added.txt
+created
*** Update File: source.txt
*** Move to: nested/target.txt
@@
 alpha
-beta
+gamma
*** End Patch""",
        agent=agent,
    )
    payload = json.loads(raw)

    assert payload["status"] == "success"
    assert not (work / "source.txt").exists()
    assert (work / "added.txt").read_text(encoding="utf-8") == "created\n"
    assert (work / "nested" / "target.txt").read_text(encoding="utf-8") == "alpha\ngamma\n"
    assert payload["files_changed"] == sorted(
        [
            str(work / "added.txt"),
            str(work / "nested" / "target.txt"),
            str(work / "source.txt"),
        ]
    )


def test_system_tools_registers_apply_patch():
    tool = BaseTool(_DummyAgent())
    tool.addTool("system_tools")

    assert "apply_patch" in system_tools.__all__
    assert "apply_patch_declaration" in system_tools.__all__
    assert "apply_patch" in tool.function_map
    assert callable(system_tools.apply_patch)
    assert any(
        item.get("function", {}).get("name") == "apply_patch"
        for item in tool.tool_declarations
    )
