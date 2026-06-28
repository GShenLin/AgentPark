from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Iterable

from nodes.agent_skill_dependencies import SkillDependencyLoadError, collect_skill_dependencies, read_skill_agent_dependencies
from src.capabilities.discovery_cache import cached_discovery_value
from src.name_lists import NameListContract, path_reference_key
from src.skills.resource_index import SkillResource, build_skill_resource_index, skill_resource_keys
from src.skills.script_manifest import SkillScriptDefinition, SkillScriptManifestError, load_skill_script_manifest


SKILL_ROOT_DIRNAME = "skills"
SKILL_FILENAME = "SKILL.md"
SKILL_OPEN_TAG = "<skills>"
SKILL_CLOSE_TAG = "</skills>"


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    path: str
    content: str
    version: str = ""
    mcp_servers: tuple[str, ...] = ()
    mcp_server_configs: dict[str, dict] = field(default_factory=dict)
    resource_root: str = ""
    resources: tuple[SkillResource, ...] = ()
    script_tools: tuple[SkillScriptDefinition, ...] = ()


class SkillLoadError(RuntimeError):
    pass


SKILL_NAME_LIST = NameListContract(
    list_label="skills",
    item_label="skill names",
    error_type=SkillLoadError,
    key_func=path_reference_key,
)


def list_available_skill_options(skill_root: str | None = None) -> list[dict[str, str]]:
    root = os.path.abspath(skill_root or default_skill_root())
    if not os.path.isdir(root):
        return []

    return cached_discovery_value("skills", root, lambda: _list_available_skill_options_uncached(root))


def _list_available_skill_options_uncached(root: str) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    root_real = os.path.realpath(root)
    for current_dir, dirnames, filenames in os.walk(root_real):
        dirnames[:] = [
            name for name in dirnames
            if _is_valid_skill_path_part(name) and not name.startswith(".")
        ]
        if SKILL_FILENAME not in filenames:
            continue
        rel = os.path.relpath(current_dir, root_real)
        if rel in {".", ""}:
            continue
        value = rel.replace(os.sep, "/")
        if not _is_valid_skill_reference(value):
            continue
        metadata = _read_skill_option_metadata(os.path.join(current_dir, SKILL_FILENAME), fallback=value)
        option = {"value": value, "label": metadata["label"]}
        if metadata["version"]:
            option["version"] = metadata["version"]
        options.append(option)
    options.sort(key=lambda item: (item["label"].casefold(), item["value"].casefold()))
    return options


def default_skill_root() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), SKILL_ROOT_DIRNAME)


def load_node_skills(
    values: object,
    *,
    node_id: object = "",
    skill_root: str | None = None,
) -> list[SkillDefinition]:
    names = SKILL_NAME_LIST.parse(values)
    if not names:
        return []

    root = os.path.abspath(skill_root or default_skill_root())
    if not os.path.isdir(root):
        raise SkillLoadError(f"skill root does not exist: {root}")

    return [_load_skill(name, root, node_id=node_id) for name in names]


def render_skill_instructions(skills: Iterable[SkillDefinition]) -> str:
    skill_list = list(skills or [])
    if not skill_list:
        return ""

    parts = [
        SKILL_OPEN_TAG,
        "The following node-scoped skills are task instructions. Skill metadata is loader state, not runtime agent state.",
        "A selected skill is not itself the user task. Use it to complete the current user request; do not stop after setup, lookup preparation, or a skill-directed tool failure with a ready/status-only response.",
        "Only capabilities exposed as tools in this node are actionable. References inside a skill to unavailable MCP servers, host commands, app connectors, or Codex-only runtime objects are informational unless the user explicitly asks to install or configure them.",
        "When a skill lists resources, read only the needed resource with read_skill_resource instead of assuming resource contents are already in this prompt.",
    ]
    for skill in skill_list:
        parts.extend(
            [
                "<skill>",
                f"<name>{_escape_tag_text(skill.name)}</name>",
                f"<description>{_escape_tag_text(skill.description)}</description>",
                f"<path>{_escape_tag_text(skill.path)}</path>",
            ]
        )
        if skill.version:
            parts.append(f"<version>{_escape_tag_text(skill.version)}</version>")
        parts.append(skill.content.rstrip())
        if skill.resources:
            parts.append("<resources>")
            for resource in skill.resources:
                parts.extend(
                    [
                        "<resource>",
                        f"<type>{_escape_tag_text(resource.type)}</type>",
                        f"<path>{_escape_tag_text(resource.path)}</path>",
                        f"<title>{_escape_tag_text(resource.title)}</title>",
                        f"<size_bytes>{resource.size_bytes}</size_bytes>",
                        f"<summary>{_escape_tag_text(resource.summary)}</summary>",
                        "</resource>",
                    ]
                )
            parts.append("</resources>")
        if skill.script_tools:
            parts.append("<script_tools>")
            for script in skill.script_tools:
                parts.extend(
                    [
                        "<script_tool>",
                        f"<id>{_escape_tag_text(script.id)}</id>",
                        f"<name>{_escape_tag_text(script.name)}</name>",
                        f"<description>{_escape_tag_text(script.description)}</description>",
                        f"<allow_write>{str(script.allow_write).lower()}</allow_write>",
                        f"<registered>{str(script.should_register).lower()}</registered>",
                        "</script_tool>",
                    ]
                )
            parts.append("</script_tools>")
        parts.append("</skill>")
    parts.append(SKILL_CLOSE_TAG)
    return "\n".join(parts)


def inject_node_skills(
    agent: object,
    values: object,
    *,
    node_id: object = "",
    skill_root: str | None = None,
    extra_skills: Iterable[SkillDefinition] | None = None,
) -> list[SkillDefinition]:
    skills = load_node_skills(values, node_id=node_id, skill_root=skill_root)
    if extra_skills:
        skills.extend(list(extra_skills))
    instructions = render_skill_instructions(skills)
    if instructions:
        agent.Message("system", instructions, persist=False)
    return skills


def inject_skill_definitions(agent: object, skills: Iterable[SkillDefinition]) -> list[SkillDefinition]:
    skill_list = list(skills or [])
    instructions = render_skill_instructions(skill_list)
    if instructions:
        agent.Message("system", instructions, persist=False)
    return skill_list


def collect_loaded_skill_dependencies(skills: Iterable[SkillDefinition]):
    return collect_skill_dependencies(tuple(skills or ()))


def load_skill_directory(
    skill_dir: str,
    *,
    node_id: object = "",
    requested_name: str | None = None,
) -> SkillDefinition:
    root = os.path.dirname(os.path.abspath(skill_dir))
    name = requested_name or os.path.basename(os.path.abspath(skill_dir))
    return _load_skill(name, root, node_id=node_id)


def _load_skill(name: str, root: str, *, node_id: object = "") -> SkillDefinition:
    skill_dir = _resolve_skill_dir(root, name, node_id=node_id)
    skill_path = os.path.join(skill_dir, SKILL_FILENAME)
    if not os.path.isfile(skill_path):
        raise SkillLoadError(_format_skill_error(node_id, name, skill_path, "SKILL.md does not exist"))

    try:
        with open(skill_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as exc:
        raise SkillLoadError(_format_skill_error(node_id, name, skill_path, f"failed to read: {exc}")) from exc

    metadata = _parse_frontmatter(content, node_id=node_id, requested_name=name, path=skill_path)
    declared_name = str(metadata.get("name") or "").strip()
    description = str(metadata.get("description") or "").strip()
    version = str(metadata.get("version") or "").strip()
    if not declared_name:
        raise SkillLoadError(_format_skill_error(node_id, name, skill_path, "missing frontmatter field `name`"))
    if not description:
        raise SkillLoadError(_format_skill_error(node_id, name, skill_path, "missing frontmatter field `description`"))

    try:
        dependencies = read_skill_agent_dependencies(skill_dir)
    except SkillDependencyLoadError as exc:
        raise SkillLoadError(_format_skill_error(node_id, name, skill_dir, str(exc))) from exc
    try:
        script_tools = load_skill_script_manifest(skill_dir, skill_name=declared_name)
    except SkillScriptManifestError as exc:
        raise SkillLoadError(_format_skill_error(node_id, name, skill_dir, str(exc))) from exc

    return SkillDefinition(
        name=declared_name,
        description=description,
        path=skill_path,
        content=_strip_frontmatter_body(content),
        version=version,
        mcp_servers=dependencies.mcp_servers,
        mcp_server_configs=dependencies.mcp_server_configs,
        resource_root=skill_dir,
        resources=build_skill_resource_index(skill_dir),
        script_tools=script_tools,
    )


def build_skill_resource_roots(skills: Iterable[SkillDefinition]) -> dict[str, str]:
    roots: dict[str, str] = {}
    for skill in skills or []:
        if not getattr(skill, "resources", None):
            continue
        root = str(getattr(skill, "resource_root", "") or os.path.dirname(os.path.abspath(skill.path))).strip()
        if not root:
            continue
        for key in skill_resource_keys(skill.name, skill.path):
            roots[key] = root
    return roots


def _resolve_skill_dir(root: str, name: str, *, node_id: object = "") -> str:
    candidate_path = os.path.join(root, name)
    if os.path.isabs(name):
        raise SkillLoadError(_format_skill_error(node_id, name, candidate_path, "skill path must be relative"))

    if not _is_valid_skill_reference(name):
        raise SkillLoadError(_format_skill_error(node_id, name, candidate_path, "invalid skill path"))
    parts = re.split(r"[\\/]+", name)

    root_real = os.path.realpath(root)
    skill_dir = os.path.realpath(os.path.join(root_real, *parts))
    if os.path.commonpath([root_real, skill_dir]) != root_real:
        raise SkillLoadError(_format_skill_error(node_id, name, skill_dir, "skill path escapes skill root"))
    return skill_dir


def _parse_frontmatter(
    content: str,
    *,
    node_id: object,
    requested_name: str,
    path: str,
) -> dict[str, str]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        raise SkillLoadError(_format_skill_error(node_id, requested_name, path, "missing YAML frontmatter"))

    end = normalized.find("\n---\n", 4)
    if end < 0:
        raise SkillLoadError(_format_skill_error(node_id, requested_name, path, "unterminated YAML frontmatter"))

    metadata: dict[str, str] = {}
    frontmatter = normalized[4:end]
    for line in frontmatter.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise SkillLoadError(_format_skill_error(node_id, requested_name, path, f"invalid frontmatter line: {line}"))
        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise SkillLoadError(_format_skill_error(node_id, requested_name, path, f"invalid frontmatter line: {line}"))
        metadata[key] = _unquote_yaml_scalar(value)
    return metadata


def _strip_frontmatter_body(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        return content
    end = normalized.find("\n---\n", 4)
    if end < 0:
        return content
    return normalized[end + len("\n---\n"):].lstrip("\n")


def _read_skill_option_metadata(path: str, *, fallback: str) -> dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        metadata = _parse_frontmatter(content, node_id="", requested_name=fallback, path=path)
        name = str(metadata.get("name") or "").strip()
        description = str(metadata.get("description") or "").strip()
        version = str(metadata.get("version") or "").strip()
        if description:
            return {"label": f"{name or fallback} - {description}", "version": version}
        return {"label": name or fallback, "version": version}
    except Exception:
        return {"label": fallback, "version": ""}


def _is_valid_skill_reference(name: str) -> bool:
    if os.path.isabs(name):
        return False
    parts = re.split(r"[\\/]+", str(name or "").strip())
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return False
    return all(_is_valid_skill_path_part(part) for part in parts)


def _is_valid_skill_path_part(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", str(value or "")))


def _unquote_yaml_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _escape_tag_text(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_skill_error(node_id: object, skill_name: str, path: str, message: str) -> str:
    node_part = f"node {node_id}: " if str(node_id or "").strip() else ""
    return f"{node_part}skill {skill_name} at {path}: {message}"
