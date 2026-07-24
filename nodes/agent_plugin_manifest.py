from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable


PLUGIN_MANIFEST_FILENAMES = ("agentpark.plugin.json", "plugin.json")


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    description: str = ""
    version: str = ""
    tools: tuple[str, ...] = ()
    public_tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    mcp_servers: tuple[str, ...] = ()
    mcp_server_configs: dict[str, dict] = field(default_factory=dict)
    config_schema: dict[str, Any] = field(default_factory=dict)
    server_api: tuple[str, ...] = ()
    source_format: str = "agentpark"


class PluginManifestError(RuntimeError):
    pass


def resolve_manifest_path(plugin_dir: str) -> str:
    for filename in PLUGIN_MANIFEST_FILENAMES:
        path = os.path.join(plugin_dir, filename)
        if os.path.isfile(path):
            return path
    return os.path.join(plugin_dir, PLUGIN_MANIFEST_FILENAMES[0])


def first_manifest_filename(filenames: Iterable[str]) -> str:
    names = set(filenames or [])
    for filename in PLUGIN_MANIFEST_FILENAMES:
        if filename in names:
            return filename
    return ""


def read_plugin_manifest(path: str) -> PluginManifest:
    raw = _read_manifest_payload(path)
    source_format = "agentpark"
    return _validate_manifest(raw, path=path, source_format=source_format)


def _read_manifest_payload(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        raise PluginManifestError(f"plugin manifest does not exist: {path}")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise PluginManifestError(
            f"plugin manifest contains invalid JSON: {path}: line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(payload, dict):
        raise PluginManifestError(f"plugin manifest must be an object: {path}")
    return payload


def _validate_manifest(
    payload: dict[str, Any],
    *,
    path: str,
    source_format: str,
) -> PluginManifest:
    plugin_id = _required_string(payload.get("id"), "id", path)
    name = _optional_string(payload.get("name"), "name", path) or plugin_id
    description = _optional_string(payload.get("description"), "description", path) or ""
    version = _optional_string(payload.get("version"), "version", path) or ""
    tools = _string_tuple(payload.get("tools"), "tools", path)
    public_tools = _string_tuple(payload.get("publicTools"), "publicTools", path)
    skills = _string_tuple(payload.get("skills"), "skills", path)
    mcp_servers, mcp_server_configs = _mcp_values(payload, path)
    config_schema = payload.get("configSchema")
    if config_schema is None:
        config_schema = {}
    if not isinstance(config_schema, dict):
        raise PluginManifestError(f"plugin manifest configSchema must be an object: {path}")
    server_api = _string_tuple(payload.get("serverApi"), "serverApi", path)
    return PluginManifest(
        id=plugin_id,
        name=name,
        description=description,
        version=version,
        tools=tools,
        public_tools=public_tools,
        skills=skills,
        mcp_servers=mcp_servers,
        mcp_server_configs=mcp_server_configs,
        config_schema=dict(config_schema),
        server_api=server_api,
        source_format=source_format,
    )


def _mcp_values(payload: dict[str, Any], path: str) -> tuple[tuple[str, ...], dict[str, dict]]:
    value = payload.get("mcpServers")
    if value is None:
        return (), {}
    if isinstance(value, list):
        return _string_tuple(value, "mcpServers", path), {}
    if isinstance(value, dict):
        return (), {"mcpServers": dict(value)}
    if isinstance(value, str):
        return (), {"mcpServers": value.strip()}
    raise PluginManifestError(f"plugin manifest mcpServers must be an array, object, or JSON file path: {path}")


def _required_string(value: object, field: str, path: str) -> str:
    text = _optional_string(value, field, path)
    if not text:
        raise PluginManifestError(f"plugin manifest missing field `{field}`: {path}")
    return text


def _optional_string(value: object, field: str, path: str) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str):
        raise PluginManifestError(f"plugin manifest field `{field}` must be a string: {path}")
    return value.strip()


def _string_tuple(value: object, field: str, path: str) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if not isinstance(value, list):
        raise PluginManifestError(f"plugin manifest field `{field}` must be an array of strings: {path}")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise PluginManifestError(f"plugin manifest field `{field}` must contain only strings: {path}")
        text = item.strip()
        if text:
            result.append(text)
    return tuple(result)
