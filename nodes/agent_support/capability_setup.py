from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Any, Callable

from nodes.agent_mcp_loader import MCP_SERVER_NAME_LIST, merge_mcp_server_settings
from nodes.agent_plugin_loader import PLUGIN_NAME_LIST, PluginCapabilitySet, resolve_plugin_capabilities
from nodes.agent_skill_loader import (
    SKILL_NAME_LIST,
    SkillDefinition,
    collect_loaded_skill_dependencies,
    load_node_skills,
    default_skill_root,
    load_skill_directory,
)
from nodes.agent_tool_loader import TOOL_NAME_LIST


@dataclass(frozen=True)
class AgentCapabilityPlan:
    plugin_names: tuple[str, ...] = ()
    selected_skill_definitions: tuple[SkillDefinition, ...] = ()
    plugin_capabilities: PluginCapabilitySet = field(default_factory=PluginCapabilitySet)
    tool_names: tuple[str, ...] = ()
    mcp_server_names: tuple[str, ...] = ()
    mcp_settings: dict[str, Any] = field(default_factory=dict)


def resolve_agent_capabilities(
    setting: Callable[[str, Any], Any],
    *,
    node_id: str,
    load_skills: Callable[..., list[SkillDefinition]] = load_node_skills,
    resolve_plugins: Callable[..., PluginCapabilitySet] = resolve_plugin_capabilities,
) -> AgentCapabilityPlan:
    plugin_names = PLUGIN_NAME_LIST.parse(setting("plugins", []))
    tool_names = TOOL_NAME_LIST.parse(setting("tools", []))
    plugin_capabilities = resolve_plugins(plugin_names, node_id=node_id)
    selected_skill_names = SKILL_NAME_LIST.parse([
        *SKILL_NAME_LIST.parse(setting("skills", [])), *plugin_capabilities.skills,
    ])
    selected_skill_definitions = load_skills(selected_skill_names, node_id=node_id)
    selected_names = {skill.name for skill in selected_skill_definitions}
    selected_names.update(skill.name for skill in plugin_capabilities.skill_definitions)
    for name in ("node-memory",):
        if name not in selected_names:
            selected_skill_definitions.append(load_skill_directory(
                os.path.join(default_skill_root(), name), node_id=node_id))
    selected_skill_dependencies = collect_loaded_skill_dependencies(selected_skill_definitions)
    mcp_server_names = MCP_SERVER_NAME_LIST.parse(setting("mcp_servers", []))
    plugin_skill_dependencies = collect_loaded_skill_dependencies(plugin_capabilities.skill_definitions)
    merged_tools = TOOL_NAME_LIST.parse([
        *tool_names, *plugin_capabilities.tools, "skill_activation_tools", "skill_resource_tools",
    ])
    merged_mcp_server_names = MCP_SERVER_NAME_LIST.parse(
        [
            *mcp_server_names,
            *plugin_capabilities.mcp_servers,
        ]
    )
    mcp_settings = merge_mcp_server_settings(plugin_capabilities.mcp_server_configs)
    mcp_settings = merge_mcp_server_settings(selected_skill_dependencies.mcp_server_configs, settings=mcp_settings)
    mcp_settings = merge_mcp_server_settings(plugin_skill_dependencies.mcp_server_configs, settings=mcp_settings)

    return AgentCapabilityPlan(
        plugin_names=tuple(plugin_names),
        selected_skill_definitions=tuple(selected_skill_definitions),
        plugin_capabilities=plugin_capabilities,
        tool_names=tuple(merged_tools),
        mcp_server_names=tuple(merged_mcp_server_names),
        mcp_settings=mcp_settings,
    )
