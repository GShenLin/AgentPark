from __future__ import annotations

from typing import Any


READ_ONLY_PREFLIGHT_TOOLS = {
    "read_file",
    "project_overview",
    "rg_search_text",
    "rg_list_files",
    "multi_tool_use_parallel",
    "execute_console_command",
}


def build_preflight_prompt(task: Any, strict: bool = False) -> str:
    base = (
        "Before you start executing the task, you must first enter an information-gathering phase.\n"
        "Requirements:\n"
        "1) Use function tools to collect key information (prefer read-only tools: project_overview/read_file/rg_list_files/rg_search_text; use execute_console_command only when necessary).\n"
        "2) Parallelize tool calls whenever possible - especially for independent file reads/searches. Use multi_tool_use_parallel to parallelize tool calls and only this.\n"
        "3) After gathering, output exactly one JSON object (no code fences, no explanations) containing: facts/assumptions/open_questions/plan.\n"
        "4) Do not deliver the final result in this phase.\n\n"
        f"Task: {task}\n"
    )
    if strict:
        return (
            "You did not call any tools as required. You must call at least one tool before outputting the JSON.\n\n"
            + base
        )
    return base


def filter_tool_declarations(declarations: list[Any], allowed_names: set[str]) -> list[dict]:
    allowed = allowed_names if isinstance(allowed_names, set) else set(allowed_names or [])
    filtered = []
    for declaration in declarations or []:
        name = None
        if isinstance(declaration, dict):
            func = declaration.get("function")
            if isinstance(func, dict):
                name = func.get("name")
            elif "name" in declaration:
                name = declaration.get("name")
        if isinstance(name, str) and name in allowed:
            filtered.append(declaration)
    return filtered


def is_safe_console_command(command: Any) -> bool:
    if not isinstance(command, str):
        return False
    cmd = command.strip().lower()
    if not cmd:
        return False

    allowed_prefixes = (
        "dir",
        "type ",
        "findstr",
        "rg ",
        "where ",
        "py ",
        "python ",
    )
    is_rg_cmd = cmd == "rg" or cmd.startswith("rg ")
    if not is_rg_cmd and not any(cmd.startswith(prefix) for prefix in allowed_prefixes):
        return False

    blocked_substrings = (
        " del ",
        " rm ",
        "rmdir",
        " move ",
        " copy ",
        " ren ",
        " mkdir",
        " rd ",
        " >",
        ">>",
        "|",
        "&",
        ";",
        "git ",
        "pip install",
        "pip uninstall",
        "npm ",
        "yarn ",
        "pnpm ",
        "curl ",
        "wget ",
        "invoke-webrequest",
        "iwr ",
    )
    return not any(item in cmd for item in blocked_substrings)
