import os

from src.capabilities.registry import CapabilityRegistry
from src.capabilities.discovery_cache import invalidate_discovery_cache
from src.mcp.tool_list_cache import invalidate_mcp_tool_list_cache
from src.tool.tool_json_response import tool_json_error, tool_json_payload
from src.web_backend.node_config_service import node_config_service


_FIELD_BY_KIND = {
    "tool": "tools",
    "mcp": "mcp_servers",
    "skill": "skills",
    "plugin": "plugins",
}
_DISCOVER_KINDS = tuple(_FIELD_BY_KIND.keys())


def _validate_action(value):
    if not isinstance(value, str):
        raise ValueError("action must be one of: discover, enable, disable")
    action = value.strip()
    if action not in {"discover", "enable", "disable"}:
        raise ValueError("action must be one of: discover, enable, disable")
    return action


def _validate_kind(value, *, action):
    if value is None:
        kind = "all"
    elif isinstance(value, str):
        kind = value.strip()
    else:
        raise ValueError("kind must be one of: all, tool, mcp, skill, plugin")
    if action == "discover" and kind == "all":
        return kind
    if kind not in _FIELD_BY_KIND:
        raise ValueError("kind must be one of: tool, mcp, skill, plugin")
    return kind


def _validate_names(values):
    if not isinstance(values, list):
        raise ValueError("names must be a non-empty list of strings")
    result = []
    seen = set()
    for item in values:
        if not isinstance(item, str):
            raise ValueError("names must contain only strings")
        name = item.strip()
        if not name:
            raise ValueError("names must contain only non-empty strings")
        if name in seen:
            raise ValueError(f"duplicate capability name: {name}")
        seen.add(name)
        result.append(name)
    if not result:
        raise ValueError("names must contain at least one non-empty string")
    return result


def _agent_memory_path(agent):
    if agent is None:
        return ""
    getter = getattr(agent, "getMemoryPath", None)
    if callable(getter):
        value = getter()
        return str(value or "").strip()
    return str(getattr(agent, "current_memory_path", "") or "").strip()


def _resolve_config_path(config_path, agent):
    direct = str(config_path or "").strip()
    if direct:
        return os.path.abspath(direct)
    memory_path = _agent_memory_path(agent)
    if not memory_path:
        raise ValueError("agent memory path is not available; pass config_path explicitly")
    return os.path.join(os.path.dirname(os.path.abspath(memory_path)), "config.json")


def _current_values(config, field):
    value = config.get(field)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"node config field {field} must be a list")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"node config field {field} must contain only strings")
        text = item.strip()
        if not text:
            raise ValueError(f"node config field {field} must contain only non-empty strings")
        if text in seen:
            raise ValueError(f"node config field {field} contains duplicate value: {text}")
        seen.add(text)
        result.append(text)
    return result


def _discover(config):
    return CapabilityRegistry().discover_payload(config)


def _mutate(config, kind, action, names):
    field = _FIELD_BY_KIND[kind]
    current = _current_values(config, field)
    before = list(current)
    if action == "enable":
        present = set(current)
        for name in names:
            if name not in present:
                current.append(name)
                present.add(name)
    elif action == "disable":
        remove = set(names)
        current = [item for item in current if item not in remove]
    else:
        raise ValueError(f"unsupported mutation action: {action}")
    config[field] = current
    return {"field": field, "before": before, "after": list(current)}


def manage_agent_capabilities(action, kind="all", names=None, config_path="", refresh=False, agent=None):
    """
    Discover, enable, or disable node-scoped tool/MCP/skill/plugin capability selections.
    """
    try:
        normalized_action = _validate_action(action)
        normalized_kind = _validate_kind(kind, action=normalized_action)
        resolved_config_path = _resolve_config_path(config_path, agent)

        if normalized_action == "discover":
            if bool(refresh):
                invalidate_discovery_cache()
                invalidate_mcp_tool_list_cache()
            config = node_config_service.read_strict(resolved_config_path)
            discovered = _discover(config)
            if normalized_kind != "all":
                discovered = {normalized_kind: discovered[normalized_kind]}
            return tool_json_payload(
                {
                    "status": "success",
                    "action": normalized_action,
                    "config_path": resolved_config_path,
                    "capabilities": discovered,
                }
            )

        if normalized_kind == "all":
            raise ValueError("kind must be specific for enable/disable")
        normalized_names = _validate_names(names)
        current_config = node_config_service.read_strict(resolved_config_path)
        CapabilityRegistry().validate_requested(normalized_kind, normalized_names, current_config)
        change_box = {}

        def mutate(config):
            change_box["change"] = _mutate(config, normalized_kind, normalized_action, normalized_names)

        result = node_config_service.update(resolved_config_path, mutate)
        change = change_box.get("change") or {}
        return tool_json_payload(
            {
                "status": "success",
                "action": normalized_action,
                "kind": normalized_kind,
                "names": normalized_names,
                "config_path": resolved_config_path,
                "change": change,
                "before": result.before,
                "after": result.after,
                "changed_fields": result.changed_fields,
                "effective": result.effective,
                "warnings": list(result.warnings),
            }
        )
    except Exception as exc:
        return tool_json_error(f"{type(exc).__name__}: {exc}", exception_type=type(exc).__name__)


manage_agent_capabilities_declaration = {
    "type": "function",
    "function": {
        "name": "manage_agent_capabilities",
        "description": (
            "Discover, enable, or disable the current Agent node's selected tool modules, MCP servers, "
            "skills, and plugins. Enable/disable updates the node config and takes effect on the next Agent run."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["discover", "enable", "disable"],
                    "description": "Operation to perform.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["all", "tool", "mcp", "skill", "plugin"],
                    "description": "Capability category. Use all only with discover.",
                    "default": "all",
                },
                "refresh": {
                    "type": "boolean",
                    "description": "Invalidate cached capability discovery data before discover.",
                    "default": False,
                },
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Capability values to enable or disable. Required for enable/disable.",
                },
                "config_path": {
                    "type": "string",
                    "description": "Optional explicit node config.json path. Defaults to the current Agent node config.",
                },
            },
            "required": ["action"],
        },
    },
}
