import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from nodes.agent_skill_activation import bind_deferred_skills
from nodes.agent_skill_loader import load_skill_directory
from src.providers.agent_runtime_context import AgentRuntimeContext, bind_agent_runtime_context
from src.tool.base_tool import BaseTool
from src.cron.tools import cron_list


def agent_for(node, **overrides):
    agent = SimpleNamespace(config={}, messages=[])
    context = dict(graph_id=node.parent.name, node_id=node.name, node_type_id="agent_node",
                   node_directory=str(node), access_role="developer")
    bind_agent_runtime_context(agent, AgentRuntimeContext(**{**context, **overrides}))
    agent.tools = BaseTool(agent)
    agent.addTool = agent.tools.addTool
    agent.Message = lambda role, content, **kw: agent.messages.append({"role": role, "content": content})
    return agent


def test_real_skill_activation_exposes_and_retracts_tools(tmp_path):
    node = tmp_path / "graph" / "agent"
    node.mkdir(parents=True)
    (node / "config.json").write_text('{"type_id":"agent_node"}', encoding="utf-8")
    agent = agent_for(node)
    skill = load_skill_directory(str(Path(__file__).resolve().parents[1] / ".agents/skills/cron"))
    assert skill.tools == ("cron_tools",)
    agent.addTool("skill_activation_tools")
    bind_deferred_skills(agent, [skill], role="developer")
    assert "cron_create" not in agent.tools.function_map
    result = json.loads(agent.tools.execute_tool("activate_skill", {"skill": "cron"}))
    assert result["status"] == "success"
    created = json.loads(agent.tools.execute_tool("cron_create", {"name": "check", "prompt": "Check status",
        "schedule": {"kind": "every", "seconds": 1800}}))
    assert created["job"]["enabled"]
    listing = json.loads(agent.tools.execute_tool("cron_list", {}))
    assert len(listing["jobs"]) == 1
    agent.tools.execute_tool("deactivate_skill", {"skill": "cron"})
    assert "cron_create" not in agent.tools.function_map
    assert len(json.loads(cron_list(agent))["jobs"]) == 1


def test_runtime_identity_and_role_are_required(tmp_path):
    node = tmp_path / "graph" / "agent"
    node.mkdir(parents=True)
    (node / "config.json").write_text('{"type_id":"agent_node"}', encoding="utf-8")
    for overrides in [{"node_id": "other"}, {"access_role": ""}, {"remote_enabled": True}]:
        with pytest.raises(ValueError):
            cron_list(agent_for(node, **overrides))


def test_tool_schemas_have_no_unresolved_references():
    from src.cron import tool_schema
    for name in ("cron_create", "cron_list", "cron_update", "cron_delete"):
        schema = getattr(tool_schema, name + "_declaration")["function"]["parameters"]
        Draft202012Validator.check_schema(schema)
        assert "$ref" not in json.dumps(schema)
