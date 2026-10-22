"""Editable model-facing tool descriptions; execution contracts stay code-owned."""
from copy import deepcopy
import re

TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")
MAX_PROMPT_CHARS = 32_000


def validate_tool_prompts(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("tool_prompts must be an object keyed by actual tool names.")
    for name, prompt in value.items():
        if not isinstance(name, str) or not TOOL_NAME.fullmatch(name):
            raise ValueError(f"Invalid tool prompt name: {name!r}")
        if not isinstance(prompt, str) or len(prompt) > MAX_PROMPT_CHARS:
            raise ValueError(f"Tool prompt {name!r} must be text of at most {MAX_PROMPT_CHARS} characters.")
    return dict(value)


def apply_tool_prompt(declaration: dict, overrides: dict[str, str]) -> dict:
    # Never mutate a module declaration or a cached MCP schema shared by agents.
    result = deepcopy(declaration)
    function = result.get("function", result)
    name = function.get("name")
    if name in overrides:
        function["description"] = overrides[name]
    return result


def prompt_catalog(tools: list[dict], controls: list[dict]) -> list[dict]:
    entries = {}
    for item in tools:
        entry = entries.setdefault(item["name"], {"name": item["name"], "defaults": []})
        entry["defaults"].append({"source": item["id"], "description": item["description"]})
    for declaration in controls:
        function = declaration["function"]
        entries[function["name"]] = {"name": function["name"], "defaults": [
            {"source": "task_control", "description": function["description"]}]
        }
    return sorted(entries.values(), key=lambda item: item["name"])
