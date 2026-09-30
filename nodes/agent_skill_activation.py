from __future__ import annotations

from collections.abc import Iterable

from nodes.agent_skill_loader import SkillDefinition


SKILL_ACTIVATION_CATALOG_TAG = "available_skill_activations"


def skill_requires_activation(skill: SkillDefinition) -> bool:
    return bool(skill.tools or skill.mcp_servers or skill.script_tools or skill.resources)


def partition_deferred_skills(
    skills: Iterable[SkillDefinition],
) -> tuple[list[SkillDefinition], list[SkillDefinition]]:
    eager: list[SkillDefinition] = []
    lazy: list[SkillDefinition] = []
    for skill in skills or []:
        (lazy if skill_requires_activation(skill) else eager).append(skill)
    return eager, lazy


def bind_deferred_skills(
    agent: object,
    skills: Iterable[SkillDefinition],
    *,
    role: str,
    mcp_settings: dict | None = None,
) -> None:
    definitions = list(skills or [])
    if not definitions:
        from src.providers.agent_runtime_context import get_agent_runtime_context
        from src.skills.activation_state import clear_active_skills
        directory = get_agent_runtime_context(agent).node_directory
        if directory:
            clear_active_skills(directory)
        return
    registry = {
        skill.name: skill
        for skill in definitions
        if isinstance(skill.name, str) and skill.name.strip()
    }
    setattr(agent, "_agentpark_available_skills", registry)
    setattr(agent, "_agentpark_skill_activation_mcp_settings", dict(mcp_settings or {}))
    from nodes.agent_skill_runtime import SkillRuntime
    runtime = SkillRuntime(agent, registry, dict(mcp_settings or {}), role)
    agent._agentpark_skill_runtime = runtime
    runtime.restore()
    if hasattr(agent, "messages"):
        agent.messages[:] = refresh_skill_messages(agent, agent.messages)
    else:
        agent.Message(role, render_skill_context(agent), persist=False)


def render_skill_context(agent: object) -> str:
    runtime = getattr(agent, "_agentpark_skill_runtime", None)
    if runtime is None:
        return ""
    lines = [
        f"<{SKILL_ACTIVATION_CATALOG_TAG}>",
        "Activate skills on demand and deactivate when done; activation persists across messages, "
        "and the current state below overrides history.",
    ]
    for skill in runtime.definitions.values():
        lines.extend([
            "<skill>",
            f"<name>{_escape(skill.name)}</name>",
            f"<description>{_escape(skill.description)}</description>",
            f"<state>{'active' if skill.name in runtime.active else 'inactive'}</state>",
        ])
        if skill.name in runtime.active:
            lines.append(f"<instructions>{_escape(skill.content)}</instructions>")
        lines.append("</skill>")
    lines.append(f"</{SKILL_ACTIVATION_CATALOG_TAG}>")
    return "\n".join(lines)


def refresh_skill_messages(agent: object, messages: list, *, responses: bool = False) -> list:
    """Replace stale capability context, including copies held by a provider loop."""
    context = render_skill_context(agent)
    if not context:
        return list(messages)
    prefix = f"<{SKILL_ACTIVATION_CATALOG_TAG}>"
    output = []
    for message in messages:
        if not isinstance(message, dict):
            output.append(message)
            continue
        content = message.get("content")
        if isinstance(content, str) and content.startswith(prefix):
            continue
        if isinstance(content, list):
            parts = [p for p in content if not (
                isinstance(p, dict) and str(p.get("text", "")).startswith(prefix)
            )]
            if content and not parts:
                continue
            message = {**message, "content": parts}
        output.append(message)
    role = agent._agentpark_skill_runtime.role
    item = {"role": role, "content": context}
    if responses:
        item = {"type": "message", "role": role, "status": "completed",
                "content": [{"type": "input_text", "text": context}]}
    return [item, *output]


def _escape(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
