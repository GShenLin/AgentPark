import json

from functions.memory_tools import search_memory


class DummyAgent:
    def __init__(self, memory_path):
        self._memory_path = str(memory_path)

    def getMemoryPath(self):
        return self._memory_path


def test_search_memory_scans_active_root_and_archives(tmp_path):
    memory_path = tmp_path / "memory.md"
    memory_path.write_text("active needle\n", encoding="utf-8")
    first_day = tmp_path / "archive" / "2026-06-20"
    second_day = tmp_path / "archive" / "2026-06-21"
    first_day.mkdir(parents=True)
    second_day.mkdir(parents=True)
    (first_day / "legacy.memory.md").write_text("legacy needle\n", encoding="utf-8")
    (second_day / "memory.md").write_text("archive needle\n", encoding="utf-8")

    payload = json.loads(search_memory("needle", max_matches=10, agent=DummyAgent(memory_path)))

    assert payload["ok"] is True
    assert payload["archive_search"] is True
    assert payload["scanned_files"] == 3
    assert payload["total_matches"] == 3
    assert [item["text"] for item in payload["matches"]] == [
        "active needle",
        "legacy needle",
        "archive needle",
    ]
    assert all("file" in item for item in payload["matches"])


def test_search_memory_explicit_file_path_keeps_single_file_behavior(tmp_path):
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("needle\n", encoding="utf-8")
    second.write_text("needle\n", encoding="utf-8")

    payload = json.loads(search_memory("needle", file_path=str(second), max_matches=10))

    assert payload["ok"] is True
    assert payload["archive_search"] is False
    assert payload["paths"] == [str(second)]
    assert payload["total_matches"] == 1
    assert payload["matches"][0]["file"] == str(second)
