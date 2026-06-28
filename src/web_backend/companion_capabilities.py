from __future__ import annotations

from typing import Any


def infer_node_can(payload: dict[str, Any]) -> dict[str, bool]:
    tools = set(_string_list(payload.get("tools")))
    tool_text = " ".join(sorted(tools)).casefold()
    mcp_servers = set(_string_list(payload.get("mcp_servers")))
    skills = set(_string_list(payload.get("skills")))
    plugins = set(_string_list(payload.get("plugins")))
    all_text = " ".join(sorted(tools | mcp_servers | skills | plugins)).casefold()
    exact_names = {_normalized_name(item) for item in tools | mcp_servers | skills | plugins}

    has_system = "system_tools" in tools
    has_rg = "rg_tools" in tools or "rg_" in tool_text
    has_file_read = "file_read_tools" in tools or "read_file" in tool_text or has_system
    has_file_write = "file_write_tools" in tools or "write_file" in tool_text or has_system
    has_shell = "console_tools" in tools or "execute_console_command" in tool_text or has_system
    has_curl = "curl_tools" in tools or "execute_curl_command" in tool_text or has_system

    return {
        "read_local_files": bool(has_file_read or has_rg),
        "write_local_files": bool(has_file_write),
        "search_local_files": bool(has_rg),
        "execute_shell": bool(has_shell),
        "web_fetch": bool(has_curl or "web" in all_text or "browser" in all_text),
        "web_search": bool("web_search" in exact_names),
        "control_aitools": bool("aitools-companion" in mcp_servers or "aitools_companion" in all_text),
        "spawn_sub_agents": bool("multi_tool_use_tools" in tools or "agent" in all_text),
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _normalized_name(value: object) -> str:
    return str(value or "").strip().casefold().replace("-", "_")


__all__ = ["infer_node_can"]
