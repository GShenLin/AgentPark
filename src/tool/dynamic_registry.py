from __future__ import annotations


def consume_registered_tool_change(agent: object, current_tools):
    if not bool(getattr(agent, "_agentpark_tool_registry_changed", False)):
        return current_tools, False
    setattr(agent, "_agentpark_tool_registry_changed", False)
    declarations = list(getattr(agent, "tool_declarations", None) or [])
    return declarations, True
