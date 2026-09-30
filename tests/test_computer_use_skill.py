import json

from nodes.agent_skill_activation import bind_deferred_skills
from nodes.agent_skill_loader import load_node_skills
from nodes.agent_support.capability_setup import resolve_agent_capabilities
from src.tool.base_tool import BaseTool


def test_computer_use_skill_loads_full_tool_loop_only_when_selected():
    without_skill = resolve_agent_capabilities(
        lambda key, default: {"tools": ["system_tools"]}.get(key, default),
        node_id="without-computer-use",
    )
    with_skill = resolve_agent_capabilities(
        lambda key, default: {
            "tools": ["system_tools"],
            "skills": ["computer-use"],
        }.get(key, default),
        node_id="with-computer-use",
    )

    assert without_skill.tool_names == ("system_tools",)
    assert with_skill.tool_names == ("system_tools", "skill_activation_tools")

    agent = type("Agent", (), {"config": {}})()
    tools = BaseTool(agent)
    agent.tools = tools
    agent.addTool = tools.addTool
    agent.Message = lambda *_args, **_kwargs: None
    for module_name in with_skill.tool_names:
        tools.addTool(module_name)

    expected = {
        "list_windows",
        "list_apps",
        "get_window",
        "launch_app",
        "activate_window",
        "get_window_state",
        "click",
        "drag",
        "scroll",
        "press_key",
        "type_text",
        "set_value",
        "perform_secondary_action",
    }
    assert "activate_skill" in tools.function_map
    assert expected.isdisjoint(tools.function_map)

    skill = load_node_skills(["computer-use"], node_id="computer-use-test")[0]
    bind_deferred_skills(agent, [skill], role="system")
    result = json.loads(tools.execute_tool("activate_skill", {"skill": "computer-use"}))

    assert result["status"] == "success"
    assert result["skill"] == "computer-use"
    assert "get_window_state" in result["tools_added"]
    assert expected.issubset(tools.function_map)
    assert agent._agentpark_tool_registry_changed is True


def test_computer_use_skill_is_discoverable_and_declares_local_tool_dependency():
    skill = load_node_skills(["computer-use"], node_id="computer-use-test")[0]

    assert skill.name == "computer-use"
    assert skill.version == "1.0.0"
    assert skill.tools == ("computer_use_tools",)
    assert "observation_id" in skill.content


def test_activation_persists_until_closed_across_agent_instances(tmp_path):
    skill = load_node_skills(["computer-use"], node_id="computer-use-test")[0]
    agents = []
    for _ in range(2):
        agent = type("Agent", (), {"config": {}, "_agentpark_node_directory": str(tmp_path)})()
        agent.tools = BaseTool(agent)
        agent.addTool = agent.tools.addTool
        agent.messages = []
        agent.Message = lambda role, content, target=agent, **_kwargs: target.messages.append({"role": role, "content": content})
        agent.addTool("skill_activation_tools")
        agents.append(agent)

    previous, current = agents
    bind_deferred_skills(previous, [skill], role="developer")
    previous_result = previous.tools.execute_tool("activate_skill", {"skill": "computer-use"})
    current.messages.append({"role": "assistant", "content": previous_result})
    bind_deferred_skills(current, [skill], role="developer")

    assert "list_windows" in previous.tools.function_map
    assert "list_windows" in current.tools.function_map
    assert "<state>active</state>" in current.messages[0]["content"]
    result = json.loads(current.tools.execute_tool("activate_skill", {"skill": "computer-use"}))
    assert result["already_active"] is True
    closed = json.loads(current.tools.execute_tool("deactivate_skill", {"skill": "computer-use"}))
    assert "list_windows" in closed["tools_removed"]
    assert "list_windows" not in current.tools.function_map
    assert "<instructions>" not in current.messages[0]["content"]
    from src.skills.activation_state import load_active_skills
    assert load_active_skills(str(tmp_path)) == set()


def test_mcp_skill_registers_server_tools_only_after_activation(monkeypatch):
    from nodes import agent_skill_runtime
    from nodes.agent_skill_loader import SkillDefinition

    calls = []
    skill = SkillDefinition(
        name="docs",
        description="Docs",
        path="skills/docs/SKILL.md",
        content="Use the docs tools.",
        mcp_servers=("docs-mcp",),
        mcp_server_configs={"docs-mcp": {"transport": "stdio", "command": "docs"}},
    )
    agent = type("Agent", (), {"config": {}})()
    tools = BaseTool(agent)
    agent.tools = tools
    agent.addTool = tools.addTool
    agent.Message = lambda *_args, **_kwargs: None
    tools.addTool("skill_activation_tools")
    bind_deferred_skills(
        agent,
        [skill],
        role="system",
        mcp_settings={"mcpServers": skill.mcp_server_configs},
    )

    def fake_register(target_agent, names, *, settings=None):
        calls.append((target_agent, names, settings))
        target_agent.tools.register_external_tool(
            {
                "type": "function",
                "function": {
                    "name": "mcp__docs__search",
                    "description": "Search docs",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            lambda: "ok",
        )
        return []

    monkeypatch.setattr(agent_skill_runtime, "register_mcp_server_tools", fake_register)

    assert "mcp__docs__search" not in tools.function_map
    result = json.loads(tools.execute_tool("activate_skill", {"skill": "docs"}))

    assert result["status"] == "success"
    assert result["tools_added"] == ["mcp__docs__search"]
    assert calls[0][1] == ["docs-mcp"]
    assert calls[0][2]["mcpServers"]["docs-mcp"]["command"] == "docs"


def test_failed_skill_activation_rolls_back_partial_tool_registration():
    from nodes.agent_skill_loader import SkillDefinition

    skill = SkillDefinition(
        name="broken",
        description="Broken dependency",
        path="skills/broken/SKILL.md",
        content="Never reached.",
        tools=("computer_use_tools", "module_that_does_not_exist"),
    )
    agent = type("Agent", (), {"config": {}})()
    tools = BaseTool(agent)
    agent.tools = tools
    agent.addTool = tools.addTool
    agent.Message = lambda *_args, **_kwargs: None
    tools.addTool("skill_activation_tools")
    bind_deferred_skills(agent, [skill], role="system")
    before = set(tools.function_map)

    result = json.loads(tools.execute_tool("activate_skill", {"skill": "broken"}))

    assert result["status"] == "exception"
    assert set(tools.function_map) == before
    assert not hasattr(agent, "_agentpark_tool_registry_changed")
