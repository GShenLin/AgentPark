from __future__ import annotations

import copy
import re
from typing import Iterable

from nodes.agent_skill_loader import SkillDefinition
from src.skills.script_manifest import SkillScriptDefinition, run_skill_script
from src.tool.tool_load_errors import ToolLoadError


class SkillScriptRegistrationError(RuntimeError):
    pass


def register_skill_script_tools(agent: object, skills: Iterable[SkillDefinition]) -> list[str]:
    register = getattr(getattr(agent, "tools", None), "register_external_tool", None)
    definitions = [
        script
        for skill in skills or []
        for script in getattr(skill, "script_tools", ()) or ()
        if getattr(script, "should_register", False)
    ]
    if not definitions:
        return []
    if not callable(register):
        raise SkillScriptRegistrationError("agent does not support skill script tool registration")

    registered: list[str] = []
    for script in definitions:
        function_name = _script_tool_name(script)
        register(_script_tool_declaration(script, function_name), _script_callable(script))
        registered.append(function_name)
    return registered


def _script_tool_name(script: SkillScriptDefinition) -> str:
    skill_part = _safe_function_part(script.skill_name, "skill name")
    script_part = _safe_function_part(script.id, "skill script id")
    return f"skill__{skill_part}__{script_part}"


def _script_tool_declaration(script: SkillScriptDefinition, function_name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": function_name,
            "description": script.description or f"Run skill script {script.id} from {script.skill_name}.",
            "parameters": copy.deepcopy(script.args_schema),
        },
    }


def _script_callable(script: SkillScriptDefinition):
    def call_skill_script(**kwargs):
        return run_skill_script(script, kwargs)

    call_skill_script.__name__ = _script_tool_name(script)
    return call_skill_script


def _safe_function_part(value: str, label: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip())
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        raise ToolLoadError(f"{label} cannot be converted to a provider-safe function name")
    return text
