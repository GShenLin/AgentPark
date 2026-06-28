from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


RESOURCE_DIR_TYPES = {
    "references": "reference",
    "scripts": "script",
    "assets": "asset",
    "agents": "agent_config",
}
DEFAULT_MAX_CHARS = 20000
HARD_MAX_CHARS = 100000
INDEX_SUMMARY_CHARS = 240


@dataclass(frozen=True)
class SkillResource:
    type: str
    path: str
    title: str
    size_bytes: int
    summary: str = ""

    def to_payload(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "path": self.path,
            "title": self.title,
            "size_bytes": self.size_bytes,
            "summary": self.summary,
        }


class SkillResourceError(RuntimeError):
    pass


def build_skill_resource_index(skill_dir: str) -> tuple[SkillResource, ...]:
    root = _real_dir(skill_dir)
    resources: list[SkillResource] = []
    for dirname, resource_type in RESOURCE_DIR_TYPES.items():
        base = os.path.join(root, dirname)
        if not os.path.isdir(base):
            continue
        for current_dir, dirnames, filenames in os.walk(base):
            dirnames[:] = [name for name in dirnames if _is_visible_path_part(name)]
            for filename in sorted(filenames):
                if not _is_visible_path_part(filename):
                    continue
                path = os.path.join(current_dir, filename)
                if not os.path.isfile(path):
                    continue
                rel_path = _relative_resource_path(root, path)
                resources.append(
                    SkillResource(
                        type=resource_type,
                        path=rel_path,
                        title=_resource_title(path, resource_type),
                        size_bytes=os.path.getsize(path),
                        summary=_resource_summary(path, resource_type),
                    )
                )
    return tuple(sorted(resources, key=lambda item: (item.type, item.path.casefold())))


def read_indexed_skill_resource(skill_dir: str, resource_path: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> dict[str, Any]:
    root = _real_dir(skill_dir)
    safe_path = _normalize_resource_path(resource_path)
    index = {resource.path: resource for resource in build_skill_resource_index(root)}
    resource = index.get(safe_path)
    if resource is None:
        raise SkillResourceError(f"skill resource is not indexed: {safe_path}")
    target = os.path.realpath(os.path.join(root, *safe_path.split("/")))
    if os.path.commonpath([root, target]) != root:
        raise SkillResourceError(f"skill resource escapes skill root: {safe_path}")
    if not os.path.isfile(target):
        raise SkillResourceError(f"skill resource does not exist: {safe_path}")

    limit = _normalize_limit(max_chars)
    content = _read_text_limited(target, limit)
    truncated = len(content) >= limit and os.path.getsize(target) > len(content.encode("utf-8", errors="replace"))
    return {
        "status": "success",
        "resource": resource.to_payload(),
        "content": content,
        "truncated": truncated,
        "max_chars": limit,
    }


def skill_resource_keys(skill_name: str, skill_path: str) -> tuple[str, ...]:
    keys: list[str] = []
    name = str(skill_name or "").strip()
    if name:
        keys.append(name)
    path = str(skill_path or "").strip()
    if path:
        skill_dir = os.path.dirname(os.path.abspath(path))
        keys.append(os.path.basename(skill_dir))
        parent = os.path.basename(os.path.dirname(skill_dir))
        if parent:
            keys.append(f"{parent}/{os.path.basename(skill_dir)}")
    result: list[str] = []
    seen: set[str] = set()
    for key in keys:
        normalized = key.replace("\\", "/").strip()
        case_key = normalized.casefold()
        if normalized and case_key not in seen:
            seen.add(case_key)
            result.append(normalized)
    return tuple(result)


def _real_dir(path: str) -> str:
    root = os.path.realpath(str(path or "").strip())
    if not root or not os.path.isdir(root):
        raise SkillResourceError(f"skill directory does not exist: {path}")
    return root


def _normalize_resource_path(path: str) -> str:
    text = str(path or "").replace("\\", "/").strip()
    if not text:
        raise SkillResourceError("resource path is required")
    if os.path.isabs(text):
        raise SkillResourceError("resource path must be relative")
    parts = [part for part in text.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise SkillResourceError("resource path must not contain . or ..")
    if parts[0] not in RESOURCE_DIR_TYPES:
        raise SkillResourceError(
            "resource path must start with one of: " + ", ".join(sorted(RESOURCE_DIR_TYPES))
        )
    return "/".join(parts)


def _relative_resource_path(root: str, path: str) -> str:
    rel = os.path.relpath(path, root).replace("\\", "/")
    return _normalize_resource_path(rel)


def _is_visible_path_part(value: str) -> bool:
    text = str(value or "")
    return bool(text) and not text.startswith(".")


def _resource_title(path: str, resource_type: str) -> str:
    if resource_type in {"asset", "script"}:
        return os.path.basename(path)
    if path.lower().endswith((".md", ".txt", ".yaml", ".yml", ".json", ".py", ".js", ".ts")):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        return stripped.lstrip("#").strip() or os.path.basename(path)
                    if stripped:
                        return stripped[:80]
        except OSError:
            return os.path.basename(path)
    return os.path.basename(path)


def _resource_summary(path: str, resource_type: str) -> str:
    if resource_type in {"asset", "script"}:
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(INDEX_SUMMARY_CHARS + 1).replace("\r", "")
    except OSError:
        return ""
    text = " ".join(part.strip() for part in text.splitlines() if part.strip())
    if len(text) > INDEX_SUMMARY_CHARS:
        return text[:INDEX_SUMMARY_CHARS] + "..."
    return text


def _normalize_limit(value: int) -> int:
    try:
        limit = int(value)
    except Exception:
        limit = DEFAULT_MAX_CHARS
    return max(1, min(limit, HARD_MAX_CHARS))


def _read_text_limited(path: str, limit: int) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read(limit)
