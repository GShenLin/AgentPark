from src.tool.dynamic_registry import consume_registered_tool_change


def test_dynamic_tool_registry_refreshes_once_after_skill_activation():
    agent = type("Agent", (), {})()
    agent.tool_declarations = [{"function": {"name": "activate_skill"}}, {"function": {"name": "click"}}]
    agent._agentpark_tool_registry_changed = True

    refreshed, changed = consume_registered_tool_change(agent, [{"function": {"name": "activate_skill"}}])
    unchanged, changed_again = consume_registered_tool_change(agent, refreshed)

    assert changed is True
    assert [item["function"]["name"] for item in refreshed] == ["activate_skill", "click"]
    assert changed_again is False
    assert unchanged is refreshed
