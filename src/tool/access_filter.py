from __future__ import annotations

from collections.abc import Iterable


NONDEVELOPER_ROLE = "nondeveloper"


def is_nondeveloper_context(context: object) -> bool:
    return (
        isinstance(context, dict)
        and str(context.get("access_role") or "").strip().lower() == NONDEVELOPER_ROLE
    )


def filter_configured_tool_modules(
    tool_names: Iterable[str],
    filtered_names: Iterable[str],
) -> tuple[str, ...]:
    blocked = _name_keys(filtered_names)
    return tuple(
        name
        for name in (str(item or "").strip() for item in tool_names or ())
        if name and name.casefold() not in blocked
    )


def filter_registered_agent_tools(agent: object, filtered_names: Iterable[str]) -> tuple[str, ...]:
    blocked = _name_keys(filtered_names)
    tools = getattr(agent, "tools", None)
    declarations = list(getattr(tools, "tool_declarations", None) or [])
    function_map = getattr(tools, "function_map", None)
    removed: list[str] = []
    kept: list[dict] = []
    for declaration in declarations:
        name = _declaration_name(declaration)
        if name and name.casefold() in blocked:
            removed.append(name)
            if isinstance(function_map, dict):
                function_map.pop(name, None)
            continue
        kept.append(declaration)
    if tools is not None:
        tools.tool_declarations = kept
    if isinstance(function_map, dict):
        for name in list(function_map):
            if str(name).strip().casefold() not in blocked:
                continue
            function_map.pop(name, None)
            if name not in removed:
                removed.append(name)
    return tuple(removed)


def _declaration_name(declaration: object) -> str:
    if not isinstance(declaration, dict):
        return ""
    function = declaration.get("function")
    if isinstance(function, dict):
        return str(function.get("name") or "").strip()
    return str(declaration.get("name") or "").strip()


def _name_keys(values: Iterable[str]) -> set[str]:
    return {
        str(value or "").strip().casefold()
        for value in values or ()
        if str(value or "").strip()
    }


__all__ = [
    "NONDEVELOPER_ROLE",
    "filter_configured_tool_modules",
    "filter_registered_agent_tools",
    "is_nondeveloper_context",
]
