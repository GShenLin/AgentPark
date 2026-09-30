"""Transactional skill activation, shared-tool ownership, and restoration."""
from __future__ import annotations

from threading import RLock

from nodes.agent_mcp_loader import McpServerLoadError, register_mcp_server_tools
from nodes.agent_mcp_results import report_mcp_load_failure
from nodes.agent_skill_loader import build_skill_resource_roots
from nodes.agent_skill_scripts import register_skill_script_tools
from src.providers.agent_runtime_context import get_agent_runtime_context
from src.skills.activation_state import load_active_skills, save_active_skills
from src.tool.base_tool import BaseTool


class _RegistrationAgent:
    """Isolate tool registration until the full capability change is valid."""

    def __init__(self, agent):
        self._owner = agent
        self.tools = BaseTool(agent)

    def __getattr__(self, name):
        return getattr(self._owner, name)

    def addTool(self, name):
        self.tools.addTool(name)


class SkillRuntime:
    def __init__(self, agent, definitions, mcp_settings, role):
        self.agent = agent
        self.definitions = definitions
        self.mcp_settings = mcp_settings
        self.role = role
        self.directory = get_agent_runtime_context(agent).node_directory
        self.lock = RLock()
        self.active = set()
        self.base_functions = dict(agent.tools.function_map)
        self.base_declarations = list(agent.tools.tool_declarations)
        self.base_roots = dict(getattr(agent, "_agentpark_skill_resource_roots", {}) or {})
        self.bundles = {}
        self.mcp_bundles = {}

    def restore(self):
        saved = load_active_skills(self.directory)
        selected = saved.intersection(self.definitions)
        if selected:
            restored = set()
            for name in sorted(selected):
                try:
                    self._bundle(name)
                except McpServerLoadError as exc:
                    report_mcp_load_failure(self.agent, exc, phase="restore_skill", skill=name)
                else:
                    restored.add(name)
            self._commit(restored, persist=False)
            # Retain failed selections so a later run can retry their MCP load.
            if selected != saved:
                save_active_skills(self.directory, selected)
        elif saved:
            save_active_skills(self.directory, set())

    def change(self, name, *, active):
        with self.lock:
            if name not in self.definitions:
                return {"status": "error", "error": f"Skill is not available: {name}",
                        "available_skills": sorted(self.definitions)}
            previous = name in self.active
            before = set(self.agent.tools.function_map)
            target = self.active | {name} if active else self.active - {name}
            if target != self.active:
                self._commit(target, persist=True)
            after = set(self.agent.tools.function_map)
            return {
                "status": "success", "skill": name, "active": active,
                "already_active" if active else "already_inactive": previous if active else not previous,
                "tools_added" if active else "tools_removed": sorted(after - before if active else before - after),
                "active_skills": sorted(self.active),
            }

    def _bundle(self, name):
        if name in self.bundles:
            return self.bundles[name]
        definition = self.definitions[name]
        target = _RegistrationAgent(self.agent)
        for module in definition.tools:
            target.addTool(module)
        for server in definition.mcp_servers:
            if server not in self.mcp_bundles:
                mcp_target = _RegistrationAgent(self.agent)
                register_mcp_server_tools(mcp_target, [server], settings=self.mcp_settings)
                self.mcp_bundles[server] = mcp_target.tools
            self._merge(target.tools, self.mcp_bundles[server])
        register_skill_script_tools(target, [definition])
        roots = build_skill_resource_roots([definition])
        if roots:
            target.addTool("skill_resource_tools")
        self.bundles[name] = (target.tools, roots)
        return self.bundles[name]

    @staticmethod
    def _merge(target, source):
        existing = {BaseTool._extract_tool_function_name(d): d for d in target.tool_declarations}
        for declaration in source.tool_declarations:
            name = BaseTool._extract_tool_function_name(declaration)
            if name in existing:
                if existing[name] != declaration:
                    raise ValueError(f"Conflicting declarations for shared skill tool: {name}")
                continue
            target.register_external_tool(declaration, source.function_map[name])
            existing[name] = declaration

    def _commit(self, names, *, persist):
        staged = BaseTool(self.agent)
        staged.function_map.update(self.base_functions)
        staged.tool_declarations.extend(self.base_declarations)
        roots = dict(self.base_roots)
        for name in sorted(names):
            tools, skill_roots = self._bundle(name)
            self._merge(staged, tools)
            roots.update(skill_roots)
        if persist:
            save_active_skills(self.directory, names)
        self.agent.tools.function_map.clear()
        self.agent.tools.function_map.update(staged.function_map)
        self.agent.tools.tool_declarations[:] = staged.tool_declarations
        self.agent._agentpark_skill_resource_roots = roots
        self.active = set(names)
        self.agent._agentpark_activated_skills = self.active
        self.agent._agentpark_tool_registry_changed = True
        # The canonical context is projected again for every provider request.
        from nodes.agent_skill_activation import refresh_skill_messages
        if hasattr(self.agent, "messages"):
            self.agent.messages[:] = refresh_skill_messages(self.agent, self.agent.messages)
