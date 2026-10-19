from __future__ import annotations

from typing import Any


def infer_node_can(payload: dict[str, Any]) -> dict[str, bool]:
    tools = set(_string_list(payload.get("tools")))
    mcp_servers = set(_string_list(payload.get("mcp_servers")))
    skills = set(_string_list(payload.get("skills")))
    plugins = set(_string_list(payload.get("plugins")))
    exact_names = tools | mcp_servers | skills | plugins

    from pathlib import Path
    from src.tool.tool_module_loader import get_functions_dir
    from src.tool.toolset_registry import load_toolset_config, resolve_toolset

    config = load_toolset_config()
    known_sets = ({path.stem for path in Path(get_functions_dir()).glob("*.py")}
                  | set(config["toolsets"])) - set(config["deleted_toolsets"])

    functions = {
        declaration.get("function", declaration)["name"]
        for toolset in tools
        if toolset in known_sets
        for declaration, _ in resolve_toolset(toolset)
    }

    return {
        "read_local_files": "read_file" in functions,
        "write_local_files": bool({"write_file", "apply_patch"} & functions),
        "search_local_files": bool({"rg_search_text", "rg_list_files"} & functions),
        "execute_shell": bool({"execute_console_command", "start_console_session"} & functions),
        "web_fetch": "execute_curl_command" in functions,
        "web_search": bool("web_search" in exact_names),
        "control_agentpark": bool("agentpark-companion" in mcp_servers),
        "spawn_sub_agents": False,
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result

__all__ = ["infer_node_can"]
