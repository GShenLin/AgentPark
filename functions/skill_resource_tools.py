import os

from nodes.agent_skill_loader import default_skill_root
from src.skills.resource_index import SkillResourceError, build_skill_resource_index, read_indexed_skill_resource
from src.tool.tool_json_response import tool_json_error, tool_json_payload


def _agent_resource_roots(agent):
    roots = getattr(agent, "_agentpark_skill_resource_roots", None) if agent is not None else None
    if not isinstance(roots, dict):
        return {}
    return {str(key): str(value) for key, value in roots.items() if str(key or "").strip() and str(value or "").strip()}


def _resolve_skill_dir(skill, agent=None):
    name = str(skill or "").replace("\\", "/").strip()
    if not name:
        raise ValueError("skill is required")
    roots = _agent_resource_roots(agent)
    if name in roots:
        return roots[name]

    root = os.path.realpath(default_skill_root())
    parts = [part for part in name.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("invalid skill name")
    candidate = os.path.realpath(os.path.join(root, *parts))
    if os.path.commonpath([root, candidate]) != root:
        raise ValueError("skill path escapes skill root")
    return candidate


def list_skill_resources(skill, agent=None):
    """
    List indexed resources for a selected skill.
    """
    try:
        skill_dir = _resolve_skill_dir(skill, agent=agent)
        resources = [item.to_payload() for item in build_skill_resource_index(skill_dir)]
        return tool_json_payload(
            {
                "status": "success",
                "skill": str(skill or "").strip(),
                "resources": resources,
            }
        )
    except Exception as exc:
        return tool_json_error(f"{type(exc).__name__}: {exc}", exception_type=type(exc).__name__)


list_skill_resources_declaration = {
    "type": "function",
    "function": {
        "name": "list_skill_resources",
        "description": "List reference, script, asset, and agent config resources indexed for a selected skill.",
        "parameters": {
            "type": "object",
            "properties": {
                "skill": {
                    "type": "string",
                    "description": "Skill name or selected skill path.",
                }
            },
            "required": ["skill"],
        },
    },
}


def read_skill_resource(skill, path, max_chars=20000, agent=None):
    """
    Read one indexed resource from a selected skill directory.
    """
    try:
        skill_dir = _resolve_skill_dir(skill, agent=agent)
        payload = read_indexed_skill_resource(skill_dir, path, max_chars=max_chars)
        payload["skill"] = str(skill or "").strip()
        return tool_json_payload(payload)
    except (SkillResourceError, ValueError) as exc:
        return tool_json_error(f"{type(exc).__name__}: {exc}", exception_type=type(exc).__name__)
    except Exception as exc:
        return tool_json_error(f"{type(exc).__name__}: {exc}", exception_type=type(exc).__name__)


read_skill_resource_declaration = {
    "type": "function",
    "function": {
        "name": "read_skill_resource",
        "description": (
            "Read a single indexed skill resource by relative path. Only resources under references/, "
            "scripts/, assets/, or agents/ are allowed, and large text is truncated."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill": {
                    "type": "string",
                    "description": "Skill name or selected skill path.",
                },
                "path": {
                    "type": "string",
                    "description": "Resource path relative to the skill directory, for example references/guide.md.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum characters to return, capped by the runtime hard limit.",
                    "default": 20000,
                },
            },
            "required": ["skill", "path"],
        },
    },
}
