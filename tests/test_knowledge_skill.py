import io
import json
from pathlib import Path
import runpy

import pytest
from pydantic import ValidationError

from nodes.agent_skill_loader import load_node_skills
from nodes.agent_skill_scripts import register_skill_script_tools
from src.knowledge.skill import execute
from src.tool.base_tool import BaseTool


def test_one_skill_registers_four_tools_with_distinct_contracts():
    class Agent:
        config = {}

    agent = Agent()
    agent.tools = BaseTool(agent)
    root = Path(__file__).resolve().parents[1]
    skills = load_node_skills(["knowledge"], node_id="test", skill_root=str(root / "skills"))
    assert register_skill_script_tools(agent, skills) == [
        "skill__knowledge__list", "skill__knowledge__search", "skill__knowledge__read",
        "skill__knowledge__table",
    ]
    declarations = {item["function"]["name"]: item["function"]["parameters"] for item in agent.tools.tool_declarations}
    assert "library_id" in declarations["skill__knowledge__list"]["properties"]
    assert set(declarations["skill__knowledge__search"]["required"]) == {"library_id", "query"}
    assert declarations["skill__knowledge__read"]["required"] == ["library_id"]
    assert declarations["skill__knowledge__read"]["oneOf"]
    assert "metrics" in declarations["skill__knowledge__table"]["required"]
    for schema in declarations.values():
        assert "action" not in schema["properties"]
        assert schema["additionalProperties"] is False


@pytest.mark.parametrize("arguments", [
    {}, {"action": "unknown"}, {"action": "search", "library_id": "a"},
    {"action": "read", "library_id": "a"}, {"action": "list", "query": "extra"},
    {"action": "read", "library_id": "a", "chunk_id": True},
    {"action": "read", "library_id": "a", "chunk_id": 1, "mode": "hybrid"},
])
def test_action_specific_arguments_are_validated_before_access(tmp_path, arguments):
    with pytest.raises(ValidationError):
        execute(tmp_path, arguments)
    assert not (tmp_path / ".auth").exists()


def test_script_dispatches_tool_identity(tmp_path, monkeypatch, capsys):
    script = Path(__file__).resolve().parents[1] / "skills" / "knowledge" / "scripts" / "query.py"
    namespace = runpy.run_path(str(script))
    namespace["main"].__globals__["WORKSPACE"] = tmp_path
    monkeypatch.setenv("AGENTPARK_SKILL_SCRIPT_ID", "list")
    monkeypatch.setattr("sys.stdin", io.StringIO('{}'))
    namespace["main"]()
    assert json.loads(capsys.readouterr().out) == {"libraries": []}


def test_script_rejects_action_override(tmp_path, monkeypatch, capsys):
    script = Path(__file__).resolve().parents[1] / "skills" / "knowledge" / "scripts" / "query.py"
    namespace = runpy.run_path(str(script))
    namespace["main"].__globals__["WORKSPACE"] = tmp_path
    monkeypatch.setenv("AGENTPARK_SKILL_SCRIPT_ID", "read")
    monkeypatch.setattr("sys.stdin", io.StringIO('{"action":"list"}'))
    with pytest.raises(SystemExit) as error:
        namespace["main"]()
    assert error.value.code == 1
    assert json.loads(capsys.readouterr().err)["type"] == "ValueError"
