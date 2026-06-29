from __future__ import annotations

import os
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from src.name_lists import NameListContract
from src.mcp.caller_context_headers import encode_caller_header_value
from src.workspace_settings import load_workspace_settings


MCP_SERVERS_CONFIG_KEYS = ("mcpServers", "mcp_servers")


@dataclass(frozen=True)
class McpServerDefinition:
    name: str
    label: str
    config: dict


class McpServerLoadError(RuntimeError):
    pass


MCP_SERVER_NAME_LIST = NameListContract(
    list_label="mcp_servers",
    item_label="MCP server names",
    error_type=McpServerLoadError,
)


def list_available_mcp_server_options(settings: dict | None = None) -> list[dict[str, str]]:
    servers = _read_mcp_server_config(settings)
    options: list[dict[str, str]] = []
    for name, config in servers.items():
        if not _is_valid_mcp_server_name(name):
            continue
        label = str((config or {}).get("label") or (config or {}).get("name") or name).strip() or name
        transport = str((config or {}).get("transport") or "").strip()
        if transport:
            label = f"{label} ({transport})"
        options.append({"value": name, "label": label})
    options.sort(key=lambda item: (item["label"].casefold(), item["value"].casefold()))
    return options


def load_mcp_server_definitions(values: object, *, settings: dict | None = None) -> list[McpServerDefinition]:
    names = MCP_SERVER_NAME_LIST.parse(values)
    if not names:
        return []

    servers = _read_mcp_server_config(settings)
    definitions: list[McpServerDefinition] = []
    for name in names:
        if not _is_valid_mcp_server_name(name):
            raise McpServerLoadError(f"invalid MCP server name: {name}")
        config = servers.get(name)
        if not isinstance(config, dict):
            raise McpServerLoadError(f"MCP server is not configured: {name}")
        label = str(config.get("label") or config.get("name") or name).strip() or name
        definitions.append(McpServerDefinition(name=name, label=label, config=dict(config)))
    return definitions


def render_mcp_server_context(servers: Iterable[McpServerDefinition]) -> str:
    server_list = list(servers or [])
    if not server_list:
        return ""
    lines = [
        "<mcp_servers>",
        "The following MCP servers are selected for this node. Their tools are exposed through provider-safe function names prefixed with mcp__<server>__ when tool listing succeeds.",
    ]
    for server in server_list:
        transport = str((server.config or {}).get("transport") or "").strip()
        lines.extend(
            [
                "<mcp_server>",
                f"<name>{_escape_tag_text(server.name)}</name>",
                f"<label>{_escape_tag_text(server.label)}</label>",
                f"<transport>{_escape_tag_text(transport)}</transport>",
                "</mcp_server>",
            ]
        )
    lines.append("</mcp_servers>")
    return "\n".join(lines)


def inject_mcp_server_context(agent: object, values: object, *, settings: dict | None = None) -> list[McpServerDefinition]:
    servers = load_mcp_server_definitions(values, settings=settings)
    context = render_mcp_server_context(servers)
    if context:
        agent.Message("system", context, persist=False)
    return servers


def register_mcp_server_tools(agent: object, values: object, *, settings: dict | None = None) -> list[McpServerDefinition]:
    servers = load_mcp_server_definitions(values, settings=settings)
    if not servers:
        return []
    register = getattr(getattr(agent, "tools", None), "register_external_tool", None)
    if not callable(register):
        raise McpServerLoadError("agent does not support external MCP tool registration")
    from nodes.agent_mcp_runtime import materialize_mcp_server_tools

    for materialized_tool in materialize_mcp_server_tools(servers):
        register(materialized_tool.declaration, materialized_tool.callable)
    return servers


def with_mcp_caller_context(settings: dict | None, *, graph_id: object, node_id: object) -> dict:
    raw_settings = dict(settings if isinstance(settings, dict) else load_workspace_settings())
    graph_text = str(graph_id or "").strip()
    node_text = str(node_id or "").strip()
    if not graph_text and not node_text:
        return raw_settings

    servers = _read_mcp_server_config(raw_settings)
    next_servers: dict[str, dict[str, Any]] = {}
    for name, config in servers.items():
        next_config = dict(config)
        if name == "aitools-companion":
            headers = next_config.get("headers")
            next_headers = dict(headers) if isinstance(headers, dict) else {}
            if graph_text:
                next_headers["x-aitools-graph-id"] = encode_caller_header_value(graph_text)
            if node_text:
                next_headers["x-aitools-node-id"] = encode_caller_header_value(node_text)
            next_config["headers"] = next_headers
        next_servers[name] = next_config
    raw_settings["mcpServers"] = next_servers
    return raw_settings


def merge_mcp_server_settings(
    extra_servers: dict[str, dict] | None,
    *,
    settings: dict | None = None,
) -> dict:
    raw_settings = dict(settings if isinstance(settings, dict) else load_workspace_settings())
    if not extra_servers:
        return raw_settings

    merged_servers = _read_mcp_server_config(raw_settings)
    for name, config in extra_servers.items():
        if name in merged_servers and _stable_json(merged_servers[name]) != _stable_json(config):
            raise McpServerLoadError(f"conflicting MCP server config: {name}")
        merged_servers[name] = dict(config)
    raw_settings["mcpServers"] = merged_servers
    return raw_settings


def _read_mcp_server_config(settings: dict | None = None) -> dict[str, dict]:
    raw_settings = settings if isinstance(settings, dict) else load_workspace_settings()
    for key in MCP_SERVERS_CONFIG_KEYS:
        value = raw_settings.get(key) if isinstance(raw_settings, dict) else None
        if isinstance(value, dict):
            return {str(name): dict(config) for name, config in value.items() if isinstance(config, dict)}
    mcp = raw_settings.get("mcp") if isinstance(raw_settings, dict) else None
    if isinstance(mcp, dict) and isinstance(mcp.get("servers"), dict):
        return {str(name): dict(config) for name, config in mcp["servers"].items() if isinstance(config, dict)}
    return {}


def _is_valid_mcp_server_name(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", str(value or "")))


def _escape_tag_text(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
