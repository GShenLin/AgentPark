from __future__ import annotations

import json


def _change_skill(skill, agent, *, active):
    runtime = getattr(agent, "_agentpark_skill_runtime", None)
    if runtime is None:
        result = {"status": "error", "error": "No on-demand skills are available in this Agent."}
    else:
        result = runtime.change(str(skill or "").strip(), active=active)
    return json.dumps(result, ensure_ascii=False)


def activate_skill(skill, agent=None):
    return _change_skill(skill, agent, active=True)


def deactivate_skill(skill, agent=None):
    return _change_skill(skill, agent, active=False)


def _lifecycle_declaration(name, description):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {"skill": {"type": "string", "description": "Exact skill name."}},
                "required": ["skill"],
                "additionalProperties": False,
            },
        },
    }


activate_skill_declaration = _lifecycle_declaration(
    "activate_skill",
    "Activate an available skill: expose its instructions and Tool/MCP declarations on the next "
    "model step. Remains active across messages until deactivated or conversation history is cleared. "
    "Reading SKILL.md does not activate it. Repeated calls are safe.",
)
deactivate_skill_declaration = _lifecycle_declaration(
    "deactivate_skill",
    "Close a skill when its work is done: remove its instructions and exclusive Tool/MCP declarations "
    "on the next model step. Shared tools remain while still needed. Repeated calls are safe.",
)

activate_skill.tool_timeout_seconds = 60
deactivate_skill.tool_timeout_seconds = 60
