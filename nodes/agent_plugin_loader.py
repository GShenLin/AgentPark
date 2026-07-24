from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Iterable

from nodes.agent_mcp_loader import MCP_SERVER_NAME_LIST
from nodes.agent_plugin_manifest import (
    PluginManifestError,
    first_manifest_filename,
    read_plugin_manifest,
    resolve_manifest_path,
)
from nodes.agent_plugin_mcp_loader import PluginMcpLoadError
from nodes.agent_plugin_mcp_loader import merge_plugin_mcp_server_configs
from nodes.agent_plugin_mcp_loader import read_plugin_mcp_refs
from nodes.agent_plugin_tool_loader import PluginToolDefinition
from nodes.agent_plugin_tool_loader import PluginToolLoadError
from nodes.agent_plugin_tool_loader import dedupe_plugin_tool_definitions
from nodes.agent_plugin_tool_loader import load_plugin_tool_path
from nodes.agent_plugin_tool_loader import materialize_plugin_tool_definitions
from nodes.agent_skill_loader import SkillDefinition, load_skill_directory
from nodes.agent_skill_loader import SKILL_NAME_LIST
from nodes.agent_tool_loader import TOOL_NAME_LIST
from src.capabilities.discovery_cache import cached_discovery_value
from src.name_lists import NameListContract, path_reference_key


PLUGIN_ROOT_DIRNAME = "plugins"


@dataclass(frozen=True)
class PluginDefinition:
    id: str
    name: str
    description: str
    path: str
    version: str = ""
    source_format: str = "agentpark"
    tools: tuple[str, ...] = ()
    tool_definitions: tuple[PluginToolDefinition, ...] = ()
    skills: tuple[str, ...] = ()
    skill_definitions: tuple[SkillDefinition, ...] = ()
    mcp_servers: tuple[str, ...] = ()
    mcp_server_configs: dict[str, dict] = field(default_factory=dict)
    config_schema: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PluginCapabilitySet:
    plugins: tuple[PluginDefinition, ...] = ()
    tools: tuple[str, ...] = ()
    tool_definitions: tuple[PluginToolDefinition, ...] = ()
    skills: tuple[str, ...] = ()
    skill_definitions: tuple[SkillDefinition, ...] = ()
    mcp_servers: tuple[str, ...] = ()
    mcp_server_configs: dict[str, dict] = field(default_factory=dict)


class PluginLoadError(RuntimeError):
    pass


PLUGIN_NAME_LIST = NameListContract(
    list_label="plugins",
    item_label="plugin ids",
    error_type=PluginLoadError,
    key_func=path_reference_key,
)


def default_plugin_root() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), PLUGIN_ROOT_DIRNAME)


def list_available_plugin_options(plugin_root: str | None = None) -> list[dict[str, str]]:
    root = os.path.abspath(plugin_root or default_plugin_root())
    if not os.path.isdir(root):
        return []

    return cached_discovery_value("plugins", root, lambda: _list_available_plugin_options_uncached(root))


def _list_available_plugin_options_uncached(root: str) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    root_real = os.path.realpath(root)
    for current_dir, dirnames, filenames in os.walk(root_real):
        dirnames[:] = [
            name for name in dirnames
            if _is_valid_path_part(name) and not name.startswith(".")
        ]
        manifest_name = first_manifest_filename(filenames)
        if not manifest_name:
            continue
        rel = os.path.relpath(current_dir, root_real)
        if rel in {".", ""}:
            continue
        value = rel.replace(os.sep, "/")
        if not _is_valid_plugin_reference(value):
            continue
        try:
            manifest = read_plugin_manifest(os.path.join(current_dir, manifest_name))
            name = manifest.name
            description = manifest.description
            label = f"{name} - {description}" if description else name
            version = manifest.version
        except Exception:
            continue
        option = {"value": value, "label": label}
        if version:
            option["version"] = version
        options.append(option)
    options.sort(key=lambda item: (item["label"].casefold(), item["value"].casefold()))
    return options


def load_node_plugins(
    values: object,
    *,
    node_id: object = "",
    plugin_root: str | None = None,
) -> list[PluginDefinition]:
    names = PLUGIN_NAME_LIST.parse(values)
    if not names:
        return []

    root = os.path.abspath(plugin_root or default_plugin_root())
    if not os.path.isdir(root):
        raise PluginLoadError(f"plugin root does not exist: {root}")

    return [_load_plugin(name, root, node_id=node_id) for name in names]


def resolve_plugin_capabilities(
    values: object,
    *,
    node_id: object = "",
    plugin_root: str | None = None,
) -> PluginCapabilitySet:
    plugins = load_node_plugins(values, node_id=node_id, plugin_root=plugin_root)
    tools: list[str] = []
    tool_definitions: list[PluginToolDefinition] = []
    skills: list[str] = []
    skill_definitions: list[SkillDefinition] = []
    mcp_servers: list[str] = []
    mcp_server_configs: dict[str, dict] = {}
    for plugin in plugins:
        tools.extend(plugin.tools)
        tool_definitions.extend(plugin.tool_definitions)
        skills.extend(plugin.skills)
        skill_definitions.extend(plugin.skill_definitions)
        mcp_servers.extend(plugin.mcp_servers)
        _merge_mcp_server_configs(mcp_server_configs, plugin.mcp_server_configs, plugin.id)
    return PluginCapabilitySet(
        plugins=tuple(plugins),
        tools=tuple(TOOL_NAME_LIST.parse(tools)),
        tool_definitions=tuple(dedupe_plugin_tool_definitions(tool_definitions)),
        skills=tuple(SKILL_NAME_LIST.parse(skills)),
        skill_definitions=tuple(_dedupe_skill_definitions(skill_definitions)),
        mcp_servers=tuple(MCP_SERVER_NAME_LIST.parse([*mcp_servers, *mcp_server_configs.keys()])),
        mcp_server_configs=mcp_server_configs,
    )


def _load_plugin(name: str, root: str, *, node_id: object = "") -> PluginDefinition:
    plugin_dir = _resolve_plugin_dir(root, name, node_id=node_id)
    manifest_path = resolve_manifest_path(plugin_dir)
    try:
        manifest = read_plugin_manifest(manifest_path)
    except PluginManifestError as exc:
        raise PluginLoadError(_format_plugin_error(node_id, name, manifest_path, str(exc))) from exc

    plugin_id = manifest.id
    tool_refs, tool_definitions = _read_tool_refs(manifest, plugin_dir, plugin_id)
    skill_refs, skill_definitions = _read_skill_refs(manifest, plugin_dir, node_id=node_id)
    mcp_server_refs, mcp_server_configs = _read_mcp_refs(manifest, plugin_dir)

    return PluginDefinition(
        id=plugin_id,
        name=manifest.name,
        description=manifest.description,
        path=manifest_path,
        version=manifest.version,
        source_format=manifest.source_format,
        tools=tuple(tool_refs),
        tool_definitions=tuple(tool_definitions),
        skills=tuple(skill_refs),
        skill_definitions=tuple(skill_definitions),
        mcp_servers=tuple(MCP_SERVER_NAME_LIST.parse([*mcp_server_refs, *mcp_server_configs.keys()])),
        mcp_server_configs=mcp_server_configs,
        config_schema=dict(manifest.config_schema or {}),
    )


def _read_tool_refs(
    manifest,
    plugin_dir: str,
    plugin_id: str,
) -> tuple[list[str], list[PluginToolDefinition]]:
    values: list[str] = []
    values.extend(str(item) for item in manifest.tools)

    refs: list[str] = []
    definitions: list[PluginToolDefinition] = []
    for item in values:
        text = str(item or "").strip()
        if not text:
            continue
        if text.startswith("./") or text.startswith(".\\"):
            try:
                definitions.extend(materialize_plugin_tool_definitions(plugin_id, load_plugin_tool_path(plugin_dir, text)))
            except PluginToolLoadError as exc:
                raise PluginLoadError(str(exc)) from exc
        else:
            refs.append(text)
    for item in manifest.public_tools:
        text = str(item or "").strip()
        if not text.startswith("./") and not text.startswith(".\\"):
            raise PluginLoadError(f"plugin publicTools must use a plugin-local path: {text!r}")
        try:
            definitions.extend(load_plugin_tool_path(plugin_dir, text))
        except PluginToolLoadError as exc:
            raise PluginLoadError(str(exc)) from exc
    return TOOL_NAME_LIST.parse(refs), dedupe_plugin_tool_definitions(definitions)


def _read_mcp_refs(manifest, plugin_dir: str) -> tuple[list[str], dict[str, dict]]:
    try:
        return read_plugin_mcp_refs(
            {"mcpServers": list(manifest.mcp_servers) if manifest.mcp_servers else manifest.mcp_server_configs.get("mcpServers")},
            plugin_dir,
        )
    except PluginMcpLoadError as exc:
        raise PluginLoadError(str(exc)) from exc


def _merge_mcp_server_configs(target: dict[str, dict], source: dict[str, dict], source_label: str) -> None:
    try:
        merge_plugin_mcp_server_configs(target, source, source_label)
    except PluginMcpLoadError as exc:
        raise PluginLoadError(str(exc)) from exc


def _read_skill_refs(
    manifest,
    plugin_dir: str,
    *,
    node_id: object,
) -> tuple[list[str], list[SkillDefinition]]:
    refs: list[str] = []
    definitions: list[SkillDefinition] = []
    for item in manifest.skills:
        text = str(item or "").strip()
        if not text:
            continue
        if text.startswith("./") or text.startswith(".\\"):
            local_path = os.path.realpath(os.path.join(plugin_dir, text))
            if not _is_inside(plugin_dir, local_path):
                raise PluginLoadError(f"plugin skill path escapes plugin root: {text}")
            definitions.extend(_load_local_skill_path(local_path, node_id=node_id))
        else:
            refs.append(text)
    return SKILL_NAME_LIST.parse(refs), _dedupe_skill_definitions(definitions)


def _load_local_skill_path(path: str, *, node_id: object) -> list[SkillDefinition]:
    if os.path.isfile(os.path.join(path, "SKILL.md")):
        return [load_skill_directory(path, node_id=node_id)]
    if not os.path.isdir(path):
        raise PluginLoadError(f"plugin skill path does not exist: {path}")
    definitions: list[SkillDefinition] = []
    for current_dir, dirnames, filenames in os.walk(path):
        dirnames[:] = [
            name for name in dirnames
            if _is_valid_path_part(name) and not name.startswith(".")
        ]
        if "SKILL.md" in filenames:
            definitions.append(load_skill_directory(current_dir, node_id=node_id))
    return definitions


def _resolve_plugin_dir(root: str, name: str, *, node_id: object = "") -> str:
    candidate_path = os.path.join(root, name)
    if os.path.isabs(name):
        raise PluginLoadError(_format_plugin_error(node_id, name, candidate_path, "plugin path must be relative"))
    if not _is_valid_plugin_reference(name):
        raise PluginLoadError(_format_plugin_error(node_id, name, candidate_path, "invalid plugin path"))
    parts = re.split(r"[\\/]+", name)
    root_real = os.path.realpath(root)
    plugin_dir = os.path.realpath(os.path.join(root_real, *parts))
    if not _is_inside(root_real, plugin_dir):
        raise PluginLoadError(_format_plugin_error(node_id, name, plugin_dir, "plugin path escapes plugin root"))
    return plugin_dir


def _dedupe_skill_definitions(skills: Iterable[SkillDefinition]) -> list[SkillDefinition]:
    result: list[SkillDefinition] = []
    seen: set[str] = set()
    for skill in skills or []:
        key = os.path.realpath(skill.path).casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(skill)
    return result


def _is_valid_plugin_reference(name: str) -> bool:
    if os.path.isabs(name):
        return False
    parts = re.split(r"[\\/]+", str(name or "").strip())
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return False
    return all(_is_valid_path_part(part) for part in parts)


def _is_valid_path_part(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", str(value or "")))


def _is_inside(root: str, candidate: str) -> bool:
    return os.path.commonpath([os.path.realpath(root), os.path.realpath(candidate)]) == os.path.realpath(root)


def _format_plugin_error(node_id: object, plugin_name: str, path: str, message: str) -> str:
    node_part = f"node {node_id}: " if str(node_id or "").strip() else ""
    return f"{node_part}plugin {plugin_name} at {path}: {message}"
