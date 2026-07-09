from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import yaml

from nodes.agent_mcp_loader import MCP_SERVER_NAME_LIST, McpServerLoadError


AGENTS_DIRNAME = "agents"
AGENT_CONFIG_EXTENSIONS = (".yaml", ".yml")
_MCP_DEPENDENCY_TYPE = "mcp"
_MCP_CONFIG_FIELDS = {
    "transport",
    "url",
    "command",
    "args",
    "env",
    "cwd",
    "headers",
    "timeout",
    "sseReadTimeout",
    "readTimeoutSeconds",
    "label",
    "name",
}
_MCP_META_FIELDS = {"type", "value", "description", "config"}


@dataclass(frozen=True)
class SkillDependencySet:
    mcp_servers: tuple[str, ...] = ()
    mcp_server_configs: dict[str, dict] = field(default_factory=dict)


class SkillDependencyLoadError(RuntimeError):
    pass


def read_skill_agent_dependencies(skill_dir: str) -> SkillDependencySet:
    agents_dir = os.path.join(os.path.realpath(skill_dir), AGENTS_DIRNAME)
    if not os.path.isdir(agents_dir):
        return SkillDependencySet()

    refs: list[str] = []
    configs: dict[str, dict] = {}
    for filename in sorted(os.listdir(agents_dir), key=str.casefold):
        if not filename.lower().endswith(AGENT_CONFIG_EXTENSIONS):
            continue
        path = os.path.realpath(os.path.join(agents_dir, filename))
        if os.path.commonpath([agents_dir, path]) != agents_dir:
            raise SkillDependencyLoadError(f"skill agent dependency path escapes agents directory: {filename}")
        payload = _read_yaml_object(path)
        dependency_set = _read_dependency_object(payload, path)
        refs.extend(dependency_set.mcp_servers)
        _merge_mcp_configs(configs, dependency_set.mcp_server_configs, path)

    return SkillDependencySet(
        mcp_servers=tuple(MCP_SERVER_NAME_LIST.parse(refs)),
        mcp_server_configs=configs,
    )


def collect_skill_dependencies(skills: list | tuple) -> SkillDependencySet:
    refs: list[str] = []
    configs: dict[str, dict] = {}
    for skill in skills or []:
        refs.extend(getattr(skill, "mcp_servers", ()) or ())
        _merge_mcp_configs(configs, getattr(skill, "mcp_server_configs", {}) or {}, getattr(skill, "path", "skill"))
    return SkillDependencySet(
        mcp_servers=tuple(MCP_SERVER_NAME_LIST.parse(refs)),
        mcp_server_configs=configs,
    )


def _read_yaml_object(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        payload = yaml.safe_load(f)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise SkillDependencyLoadError(f"skill agent dependency file must contain an object: {path}")
    return payload


def _read_dependency_object(payload: dict, path: str) -> SkillDependencySet:
    dependencies = payload.get("dependencies")
    if dependencies is None:
        return SkillDependencySet()
    if not isinstance(dependencies, dict):
        raise SkillDependencyLoadError(f"dependencies must be an object: {path}")

    tools = dependencies.get("tools")
    if tools is None:
        return SkillDependencySet()
    if not isinstance(tools, list):
        raise SkillDependencyLoadError(f"dependencies.tools must be a list: {path}")

    refs: list[str] = []
    configs: dict[str, dict] = {}
    for index, item in enumerate(tools):
        if not isinstance(item, dict):
            raise SkillDependencyLoadError(f"dependencies.tools[{index}] must be an object: {path}")
        dependency_type = str(item.get("type") or "").strip()
        if dependency_type != _MCP_DEPENDENCY_TYPE:
            continue
        name = str(item.get("value") or "").strip()
        if not name:
            raise SkillDependencyLoadError(f"dependencies.tools[{index}].value is required for MCP: {path}")
        refs.append(name)
        config = _read_mcp_dependency_config(item, path, index)
        if config:
            _merge_mcp_configs(configs, {name: config}, path)

    try:
        normalized_refs = tuple(MCP_SERVER_NAME_LIST.parse(refs))
    except McpServerLoadError as exc:
        raise SkillDependencyLoadError(str(exc)) from exc
    return SkillDependencySet(mcp_servers=normalized_refs, mcp_server_configs=configs)


def _read_mcp_dependency_config(item: dict, path: str, index: int) -> dict:
    unknown_fields = set(item.keys()) - _MCP_META_FIELDS - _MCP_CONFIG_FIELDS
    if unknown_fields:
        fields = ", ".join(sorted(str(field) for field in unknown_fields))
        raise SkillDependencyLoadError(f"unsupported MCP dependency fields at dependencies.tools[{index}]: {fields}")

    config = item.get("config")
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise SkillDependencyLoadError(f"dependencies.tools[{index}].config must be an object: {path}")
    result = dict(config)
    for field in _MCP_CONFIG_FIELDS:
        if field in item:
            result[field] = item[field]
    if "description" in item and "label" not in result:
        result["label"] = str(item.get("description") or "").strip()
    if "transport" in result:
        result["transport"] = _validate_transport(result["transport"])
    return result


def _validate_transport(value: object) -> str:
    if not isinstance(value, str):
        raise SkillDependencyLoadError("MCP dependency transport must be a string")
    text = value.strip()
    if text not in {"stdio", "sse", "streamable-http"}:
        raise SkillDependencyLoadError(f"MCP dependency transport is unsupported: {text}")
    return text


def _merge_mcp_configs(target: dict[str, dict], source: dict[str, dict], source_label: str) -> None:
    for name, config in (source or {}).items():
        if name in target and _stable_json(target[name]) != _stable_json(config):
            raise SkillDependencyLoadError(f"conflicting MCP server config for {name} from {source_label}")
        target[name] = dict(config)


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
