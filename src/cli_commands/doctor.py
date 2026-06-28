from __future__ import annotations

import json
import os
import platform
import re
import shutil
from typing import Any

from src.config_loader import ConfigLoader
from src.workspace_settings import load_workspace_settings
from src.web_backend.graph_runtime_registry import GraphConfigReadError
from src.web_backend import runtime_paths
from src.web_backend.node_config_errors import NodeConfigReadError
from src.web_backend.node_config_service import node_config_service
from nodes.agent_mcp_loader import MCP_SERVERS_CONFIG_KEYS
from nodes.agent_plugin_loader import default_plugin_root, list_available_plugin_options, load_node_plugins
from nodes.agent_skill_loader import default_skill_root, list_available_skill_options, load_node_skills


def run_doctor(_args) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.append(_check_python())
    checks.append(_check_executable("node"))
    checks.append(_check_executable("npm"))
    checks.append(_check_executable("rg"))
    checks.append(_check_workspace_config())
    checks.append(_check_provider_config())
    checks.append(_check_companion_config())
    checks.extend(_check_mcp_server_manifests())
    checks.extend(_check_skill_manifests())
    checks.extend(_check_plugin_manifests())
    checks.extend(_check_graph_configs())
    checks.extend(_check_node_configs())
    ok = all(item.get("status") == "ok" for item in checks)
    return {"status": "success" if ok else "error", "ok": ok, "checks": checks}


def _check_python() -> dict[str, Any]:
    version = platform.python_version()
    return {"name": "python", "status": "ok", "detail": version}


def _check_executable(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    return {
        "name": name,
        "status": "ok" if path else "error",
        "detail": path or f"{name} was not found on PATH",
    }


def _check_workspace_config() -> dict[str, Any]:
    try:
        ConfigLoader().get_config()
        return {"name": "workspace_config", "status": "ok", "detail": "config loaded"}
    except Exception as exc:
        return {"name": "workspace_config", "status": "error", "detail": f"{type(exc).__name__}: {exc}"}


def _check_provider_config() -> dict[str, Any]:
    try:
        providers = ConfigLoader().get_all_providers()
    except Exception as exc:
        return {"name": "providers", "status": "error", "detail": f"{type(exc).__name__}: {exc}"}
    if not isinstance(providers, dict):
        return {"name": "providers", "status": "error", "detail": "providers must be an object"}
    return {"name": "providers", "status": "ok", "detail": f"{len(providers)} provider(s) loaded"}


def _check_companion_config() -> dict[str, Any]:
    path = os.path.join(runtime_paths._get_graphs_dir(), "companion", "config.json")
    try:
        payload = node_config_service.read_strict(path)
    except NodeConfigReadError as exc:
        return {"name": "companion_config", "status": "error", "detail": str(exc), "path": path}
    if str(payload.get("type_id") or "agent_node").strip() != "agent_node":
        return {"name": "companion_config", "status": "error", "detail": "type_id must be agent_node", "path": path}
    if not str(payload.get("provider_id") or "").strip():
        return {"name": "companion_config", "status": "error", "detail": "provider_id is required", "path": path}
    return {"name": "companion_config", "status": "ok", "detail": path}


def _check_mcp_server_manifests() -> list[dict[str, Any]]:
    try:
        settings = load_workspace_settings()
        servers = _raw_mcp_server_config(settings)
    except Exception as exc:
        return [{"name": "mcp_servers", "status": "error", "detail": f"{type(exc).__name__}: {exc}"}]
    if not servers:
        return [{"name": "mcp_servers", "status": "ok", "detail": "no MCP servers configured"}]

    checks: list[dict[str, Any]] = []
    for name, config in sorted(servers.items(), key=lambda item: str(item[0]).casefold()):
        check_name = f"mcp_server:{name}"
        try:
            _validate_mcp_server_manifest(str(name), config)
            checks.append({"name": check_name, "status": "ok", "detail": "configured"})
        except Exception as exc:
            checks.append({"name": check_name, "status": "error", "detail": str(exc)})
    return checks


def _check_skill_manifests() -> list[dict[str, Any]]:
    root = default_skill_root()
    if not os.path.isdir(root):
        return [{"name": "skills", "status": "ok", "detail": f"skill root does not exist: {root}"}]
    try:
        options = list_available_skill_options(root)
    except Exception as exc:
        return [{"name": "skills", "status": "error", "detail": f"{type(exc).__name__}: {exc}", "path": root}]
    if not options:
        return [{"name": "skills", "status": "ok", "detail": "no skills found", "path": root}]

    checks: list[dict[str, Any]] = []
    for option in options:
        value = str(option.get("value") or "").strip()
        if not value:
            continue
        try:
            load_node_skills([value], skill_root=root)
            checks.append({"name": f"skill:{value}", "status": "ok", "detail": "loaded"})
        except Exception as exc:
            checks.append(
                {
                    "name": f"skill:{value}",
                    "status": "error",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "path": os.path.join(root, *re.split(r"[\\/]+", value), "SKILL.md"),
                }
            )
    return checks


def _check_plugin_manifests() -> list[dict[str, Any]]:
    root = default_plugin_root()
    if not os.path.isdir(root):
        return [{"name": "plugins", "status": "ok", "detail": f"plugin root does not exist: {root}"}]
    try:
        options = list_available_plugin_options(root)
    except Exception as exc:
        return [{"name": "plugins", "status": "error", "detail": f"{type(exc).__name__}: {exc}", "path": root}]
    if not options:
        return [{"name": "plugins", "status": "ok", "detail": "no plugins found", "path": root}]

    checks: list[dict[str, Any]] = []
    for option in options:
        value = str(option.get("value") or "").strip()
        if not value:
            continue
        try:
            load_node_plugins([value], plugin_root=root)
            checks.append({"name": f"plugin:{value}", "status": "ok", "detail": "loaded"})
        except Exception as exc:
            checks.append(
                {
                    "name": f"plugin:{value}",
                    "status": "error",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "path": os.path.join(root, *re.split(r"[\\/]+", value)),
                }
            )
    return checks


def _check_graph_configs() -> list[dict[str, Any]]:
    graphs_dir = runtime_paths._get_graphs_dir()
    if not os.path.isdir(graphs_dir):
        return [{"name": "graph_configs", "status": "ok", "detail": f"graphs directory does not exist: {graphs_dir}"}]

    checks: list[dict[str, Any]] = []
    for graph_id in sorted(os.listdir(graphs_dir)):
        if graph_id == "companion":
            continue
        graph_dir = os.path.join(graphs_dir, graph_id)
        if not os.path.isdir(graph_dir):
            continue
        config_path = os.path.join(graph_dir, "config.json")
        if not os.path.isfile(config_path):
            continue
        name = f"graph_config:{graph_id}"
        try:
            _read_graph_config_file(config_path)
            checks.append({"name": name, "status": "ok", "detail": config_path})
        except GraphConfigReadError as exc:
            checks.append({"name": name, "status": "error", "detail": str(exc), "path": config_path})
    if not checks:
        checks.append({"name": "graph_configs", "status": "ok", "detail": "no graph configs found"})
    return checks


def _check_node_configs() -> list[dict[str, Any]]:
    graphs_dir = runtime_paths._get_graphs_dir()
    if not os.path.isdir(graphs_dir):
        return [{"name": "node_configs", "status": "ok", "detail": f"graphs directory does not exist: {graphs_dir}"}]

    checks: list[dict[str, Any]] = []
    for graph_id in sorted(os.listdir(graphs_dir)):
        graph_dir = os.path.join(graphs_dir, graph_id)
        if not os.path.isdir(graph_dir):
            continue
        for node_id in sorted(os.listdir(graph_dir)):
            config_path = os.path.join(graph_dir, node_id, "config.json")
            if not os.path.isfile(config_path):
                continue
            name = f"node_config:{graph_id}/{node_id}"
            try:
                node_config_service.read_strict(config_path)
                checks.append({"name": name, "status": "ok", "detail": config_path})
            except NodeConfigReadError as exc:
                checks.append({"name": name, "status": "error", "detail": str(exc), "path": config_path})
    if not checks:
        checks.append({"name": "node_configs", "status": "ok", "detail": "no node configs found"})
    return checks


def _read_graph_config_file(config_path: str) -> dict[str, Any]:
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise GraphConfigReadError(
            f"graph config contains invalid JSON: {config_path}: line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise GraphConfigReadError(
            f"failed to read graph config {config_path}: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise GraphConfigReadError(f"graph config must be a JSON object: {config_path}")
    return payload


def _raw_mcp_server_config(settings: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(settings, dict):
        return {}
    for key in MCP_SERVERS_CONFIG_KEYS:
        value = settings.get(key)
        if value is not None:
            if not isinstance(value, dict):
                raise ValueError(f"config/config.json field {key} must be an object")
            return dict(value)
    mcp = settings.get("mcp")
    if isinstance(mcp, dict) and mcp.get("servers") is not None:
        servers = mcp.get("servers")
        if not isinstance(servers, dict):
            raise ValueError("config/config.json field mcp.servers must be an object")
        return dict(servers)
    return {}


def _validate_mcp_server_manifest(name: str, config: Any) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError(f"invalid MCP server name: {name}")
    if not isinstance(config, dict):
        raise ValueError(f"MCP server {name} config must be an object")
    transport = str(config.get("transport") or config.get("type") or "stdio").strip().lower().replace("_", "-")
    if transport == "http":
        transport = "streamable-http"
    if transport not in {"stdio", "sse", "streamable-http"}:
        raise ValueError(f"MCP server {name} transport is unsupported: {transport}")
    if transport == "stdio" and not str(config.get("command") or "").strip():
        raise ValueError(f"MCP server {name} field command is required for stdio transport")
    if transport in {"sse", "streamable-http"} and not str(config.get("url") or "").strip():
        raise ValueError(f"MCP server {name} field url is required for {transport} transport")
    for field in ("args",):
        value = config.get(field)
        if value not in (None, "") and (not isinstance(value, list) or not all(isinstance(item, str) for item in value)):
            raise ValueError(f"MCP server {name} field {field} must be a string array")
    for field in ("env", "headers"):
        value = config.get(field)
        if value not in (None, "") and (
            not isinstance(value, dict)
            or not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items())
        ):
            raise ValueError(f"MCP server {name} field {field} must be an object of string values")
