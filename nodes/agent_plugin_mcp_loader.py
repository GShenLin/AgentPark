from __future__ import annotations

import json
import os

from nodes.agent_mcp_loader import MCP_SERVER_NAME_LIST


class PluginMcpLoadError(RuntimeError):
    pass


def read_plugin_mcp_refs(manifest: dict, plugin_dir: str) -> tuple[list[str], dict[str, dict]]:
    refs: list[str] = []
    configs: dict[str, dict] = {}
    value = manifest.get("mcpServers")
    if isinstance(value, list):
        refs.extend(str(item) for item in value)
    elif isinstance(value, dict):
        merge_plugin_mcp_server_configs(configs, _read_mcp_config_map(value, plugin_dir), "mcpServers")
    elif isinstance(value, str) and value.strip():
        merge_plugin_mcp_server_configs(configs, _read_mcp_config_file(plugin_dir, value), "mcpServers")
    return refs, configs


def merge_plugin_mcp_server_configs(target: dict[str, dict], source: dict[str, dict], source_label: str) -> None:
    for name, config in (source or {}).items():
        if name in target and _stable_json(target[name]) != _stable_json(config):
            raise PluginMcpLoadError(f"conflicting MCP server config for {name} from {source_label}")
        target[name] = dict(config)


def _read_mcp_config_file(plugin_dir: str, value: str) -> dict[str, dict]:
    text = value.strip()
    if not text:
        return {}
    if os.path.isabs(text):
        raise PluginMcpLoadError(f"plugin mcpServers path must be relative: {text}")
    if not text.endswith(".json"):
        raise PluginMcpLoadError(f"plugin mcpServers file must be JSON: {text}")
    base = os.path.realpath(plugin_dir)
    path = os.path.realpath(os.path.join(base, text))
    if not _is_inside(base, path):
        raise PluginMcpLoadError(f"plugin mcpServers path escapes plugin root: {text}")
    if not os.path.isfile(path):
        raise PluginMcpLoadError(f"plugin mcpServers file does not exist: {path}")
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise PluginMcpLoadError(f"plugin mcpServers file must contain an object: {path}")
    return _read_mcp_config_map(payload, os.path.dirname(path))


def _read_mcp_config_map(value: dict, base_dir: str) -> dict[str, dict]:
    nested = value.get("mcpServers")
    if not isinstance(nested, dict):
        nested = value
    result: dict[str, dict] = {}
    for name, config in nested.items():
        server_name = str(name or "").strip()
        if not server_name:
            continue
        if not isinstance(config, dict):
            raise PluginMcpLoadError(f"plugin MCP server config must be an object: {server_name}")
        if config.get("enabled") is False:
            continue
        result[server_name] = _absolutize_plugin_mcp_server_config(config, base_dir)
    MCP_SERVER_NAME_LIST.parse(list(result.keys()))
    return result


def _absolutize_plugin_mcp_server_config(config: dict, base_dir: str) -> dict:
    result = dict(config)
    if "cwd" not in result and "workingDirectory" not in result:
        result["cwd"] = os.path.realpath(base_dir)
    for key in ("command", "cwd", "workingDirectory"):
        if isinstance(result.get(key), str):
            result[key] = _resolve_plugin_mcp_path(str(result[key]), base_dir)
    if isinstance(result.get("args"), list):
        result["args"] = [
            _resolve_plugin_mcp_path(item, base_dir) if isinstance(item, str) else item
            for item in result["args"]
        ]
    if isinstance(result.get("env"), dict):
        result["env"] = {
            key: _resolve_plugin_mcp_path(item, base_dir) if isinstance(item, str) else item
            for key, item in result["env"].items()
        }
    return result


def _resolve_plugin_mcp_path(value: str, base_dir: str) -> str:
    text = value.strip()
    if (
        text.startswith("./")
        or text.startswith(".\\")
        or text.startswith("../")
        or text.startswith("..\\")
        or text in {".", ".."}
    ):
        resolved = os.path.realpath(os.path.join(base_dir, text))
        if not _is_inside(base_dir, resolved):
            raise PluginMcpLoadError(f"plugin MCP path escapes plugin root: {text}")
        return resolved
    return os.path.abspath(text) if os.path.isabs(text) else text


def _is_inside(root: str, candidate: str) -> bool:
    return os.path.commonpath([os.path.realpath(root), os.path.realpath(candidate)]) == os.path.realpath(root)


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
