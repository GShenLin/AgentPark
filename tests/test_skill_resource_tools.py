import json

from functions.skill_resource_tools import list_skill_resources, read_skill_resource
from src.skills.resource_index import SkillResourceError, read_indexed_skill_resource


def _write_skill_dir(tmp_path):
    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo\n---\n\nUse this skill.\n",
        encoding="utf-8",
    )
    refs = skill_dir / "references"
    refs.mkdir()
    (refs / "guide.md").write_text("# Guide\n\nRead this reference.\n", encoding="utf-8")
    return skill_dir


class Agent:
    def __init__(self, skill_dir):
        self._agentpark_skill_resource_roots = {"demo": str(skill_dir)}


def test_list_and_read_skill_resource_from_agent_bound_roots(tmp_path):
    skill_dir = _write_skill_dir(tmp_path)
    agent = Agent(skill_dir)

    listed = json.loads(list_skill_resources("demo", agent=agent))
    assert listed["status"] == "success"
    assert listed["resources"][0]["path"] == "references/guide.md"

    read = json.loads(read_skill_resource("demo", "references/guide.md", agent=agent))
    assert read["status"] == "success"
    assert read["resource"]["type"] == "reference"
    assert "Read this reference." in read["content"]


def test_read_skill_resource_rejects_path_escape(tmp_path):
    skill_dir = _write_skill_dir(tmp_path)
    payload = json.loads(read_skill_resource("demo", "../outside.txt", agent=Agent(skill_dir)))

    assert payload["status"] == "error"
    assert payload["exception_type"] == "SkillResourceError"


def test_read_indexed_skill_resource_truncates_large_file(tmp_path):
    skill_dir = _write_skill_dir(tmp_path)
    large = skill_dir / "references" / "large.txt"
    large.write_text("abcdef", encoding="utf-8")

    payload = read_indexed_skill_resource(str(skill_dir), "references/large.txt", max_chars=3)

    assert payload["status"] == "success"
    assert payload["content"] == "abc"
    assert payload["truncated"] is True


def test_read_indexed_skill_resource_rejects_unindexed_file(tmp_path):
    skill_dir = _write_skill_dir(tmp_path)
    (skill_dir / "notes.txt").write_text("not indexed", encoding="utf-8")

    try:
        read_indexed_skill_resource(str(skill_dir), "notes.txt")
    except SkillResourceError as exc:
        assert "must start with one of" in str(exc) or "not indexed" in str(exc)
    else:
        raise AssertionError("expected SkillResourceError")
