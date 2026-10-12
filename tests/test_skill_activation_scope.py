import pytest

from nodes.agent_skill_loader import SkillLoadError, load_skill_directory


@pytest.mark.parametrize("value,expected", [(None, "turn"), ("turn", "turn"),
                                           ("conversation", "conversation")])
def test_activation_scope_is_loaded(tmp_path, value, expected):
    path = tmp_path / "demo"
    path.mkdir()
    metadata = "" if value is None else f"metadata:\n  activation_scope: {value}\n"
    (path / "SKILL.md").write_text(
        f"---\nname: demo\ndescription: Test\n{metadata}---\nInstructions.\n", encoding="utf-8")
    assert load_skill_directory(str(path)).activation_scope == expected


@pytest.mark.parametrize("value", ["always", "false", "null", "[]", "{}"])
def test_invalid_scope_is_reported(tmp_path, value):
    path = tmp_path / "demo"
    path.mkdir()
    (path / "SKILL.md").write_text(
        f"---\nname: demo\ndescription: Test\nmetadata:\n  activation_scope: {value}\n---\nTest.\n",
        encoding="utf-8")
    with pytest.raises(SkillLoadError, match="metadata.activation_scope"):
        load_skill_directory(str(path))
