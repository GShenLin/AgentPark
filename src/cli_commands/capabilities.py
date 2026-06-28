from __future__ import annotations

from typing import Any

from src.capabilities.discovery_cache import invalidate_discovery_cache
from src.capabilities.registry import CapabilityRegistry
from src.mcp.tool_list_cache import invalidate_mcp_tool_list_cache
from src.web_backend.node_config_service import node_config_service

from .common import node_config_path


FIELD_BY_KIND = {
    "tool": "tools",
    "mcp": "mcp_servers",
    "skill": "skills",
    "plugin": "plugins",
}


def list_capabilities(args) -> dict[str, Any]:
    if bool(getattr(args, "refresh", False)):
        invalidate_discovery_cache()
        invalidate_mcp_tool_list_cache()
    path = node_config_path(args.graph, args.node)
    config = node_config_service.read_strict(path)
    return {
        "status": "success",
        "config_path": path,
        "capabilities": CapabilityRegistry().discover_payload(config),
    }


def mutate_capability(args) -> dict[str, Any]:
    path = node_config_path(args.graph, args.node)
    kind = str(args.kind or "").strip().lower()
    if kind not in FIELD_BY_KIND:
        raise ValueError("kind must be one of: tool, mcp, skill, plugin")
    names = [str(item).strip() for item in (args.name or []) if str(item).strip()]
    if not names:
        raise ValueError("--name is required")

    current = node_config_service.read_strict(path)
    CapabilityRegistry().validate_requested(kind, names, current)
    field = FIELD_BY_KIND[kind]

    def mutate(config: dict[str, Any]) -> None:
        selected = _current_values(config.get(field))
        selected_keyed = {item.casefold(): item for item in selected}
        if args.capability_action == "enable":
            for name in names:
                selected_keyed.setdefault(name.casefold(), name)
            config[field] = list(selected_keyed.values())
        elif args.capability_action == "disable":
            remove = {name.casefold() for name in names}
            config[field] = [item for item in selected if item.casefold() not in remove]
        else:
            raise ValueError(f"unsupported capability action: {args.capability_action}")

    result = node_config_service.update(path, mutate)
    return {"status": "success", "action": args.capability_action, "kind": kind, "names": names, **result.to_payload()}


def _current_values(value: object) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValueError("capability field must be a list")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError("capability field must contain only strings")
        text = item.strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result
