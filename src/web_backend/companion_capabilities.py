from __future__ import annotations

from typing import Any


def infer_node_can(payload: dict[str, Any]) -> dict[str, bool]:
    tools = set(_string_list(payload.get("tools")))
    mcp_servers = set(_string_list(payload.get("mcp_servers")))
    skills = set(_string_list(payload.get("skills")))
    plugins = set(_string_list(payload.get("plugins")))
    exact_names = tools | mcp_servers | skills | plugins

    has_system = "system_tools" in tools
    has_rg = "rg_tools" in tools
    has_file_read = "file_read_tools" in tools or has_system
    has_file_write = "file_write_tools" in tools or has_system
    has_shell = "console_tools" in tools or has_system
    has_curl = "network_tools" in tools or "curl_tools" in tools

    return {
        "read_local_files": bool(has_file_read or has_rg),
        "write_local_files": bool(has_file_write),
        "search_local_files": bool(has_rg),
        "execute_shell": bool(has_shell),
        "web_fetch": bool(has_curl),
        "web_search": bool("web_search" in exact_names),
        "control_agentpark": bool("agentpark-companion" in mcp_servers),
        "spawn_sub_agents": bool("multi_tool_use_tools" in tools),
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
