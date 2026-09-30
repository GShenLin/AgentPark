"""Project skill inventory. Category folders and skill bundles have distinct roles."""
from __future__ import annotations

import re
from pathlib import Path

from nodes.agent_skill_loader import (
    SkillLoadError, _is_valid_skill_reference, _parse_frontmatter,
    load_node_skills,
)


class SkillCatalogError(ValueError):
    pass


def is_link(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


class SkillCatalog:
    def __init__(self, root: Path):
        self.root = root.absolute()

    def resolve(self, reference: str, *, allow_root: bool = False) -> Path:
        if not reference and allow_root:
            candidate = self.root
        else:
            if not _is_valid_skill_reference(reference) or "\\" in reference or "//" in reference or reference != reference.strip():
                raise SkillCatalogError("目录名称须以英文字母或数字开头，仅可包含字母、数字、下划线、短横线和点；层级用 / 分隔。")
            for part in reference.split("/"):
                if part.endswith(".") or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part):
                    raise SkillCatalogError("文件夹名不能以点结尾或使用系统保留名称。")
            candidate = self.root.joinpath(*reference.split("/"))
        # Reject links at every level, including a linked skill root or .agents.
        if any(is_link(p) for p in (candidate, *candidate.parents)):
            raise SkillCatalogError("链接或 junction 目录不能通过 Skill 管理页操作。")
        if not candidate.resolve().is_relative_to(self.root.resolve()):
            raise SkillCatalogError("路径超出项目 Skill 目录。")
        return candidate

    def entries(self) -> list[dict]:
        self.resolve("", allow_root=True)
        if not self.root.exists():
            return []
        entries: list[dict] = []

        def visit(parent: Path) -> None:
            for path in sorted(parent.iterdir(), key=lambda p: p.name.casefold()):
                if path.name.startswith(".") or not path.is_dir():
                    continue
                relative = path.relative_to(self.root).as_posix()
                issue = ""
                try:
                    self.resolve(relative)
                except SkillCatalogError as exc:
                    issue = str(exc)
                kind = "skill" if (path / "SKILL.md").is_file() else "folder"
                entry = dict(path=relative, parent=parent.relative_to(self.root).as_posix(),
                             kind=kind, name=path.name, description="", version="", error=issue,
                             skill_count=0, folder_count=0)
                if entry["parent"] == ".":
                    entry["parent"] = ""
                entries.append(entry)
                if issue:
                    continue
                if kind == "skill":
                    try:
                        document = path / "SKILL.md"
                        if is_link(document):
                            raise SkillCatalogError("SKILL.md 为链接，无法读取。")
                        metadata = _parse_frontmatter(document.read_text(encoding="utf-8"),
                                                      node_id="", requested_name=relative, path=str(document))
                        for field in ("name", "description"):
                            if not isinstance(metadata.get(field), str) or not metadata[field].strip():
                                raise SkillCatalogError(f"SKILL.md 缺少 {field}。")
                        version = metadata.get("version", "")
                        if type(version) not in (str, int, float):
                            raise SkillCatalogError("SKILL.md version 必须是文本或数字。")
                        entry.update(name=metadata["name"], description=metadata["description"], version=str(version))
                    except (SkillLoadError, SkillCatalogError, OSError, UnicodeError) as exc:
                        entry["error"] = str(exc)
                else:
                    visit(path)

        visit(self.root)
        by_path = {entry["path"]: entry for entry in entries}
        for entry in reversed(entries):
            parent = by_path.get(entry["parent"])
            if parent:
                parent["skill_count"] += entry["skill_count"] + int(entry["kind"] == "skill")
                parent["folder_count"] += entry["folder_count"] + int(entry["kind"] == "folder")
        return entries

    def detail(self, reference: str) -> dict:
        folder = self.resolve(reference)
        document = folder / "SKILL.md"
        if not document.is_file():
            raise FileNotFoundError("Skill 不存在。")
        if is_link(document):
            raise SkillCatalogError("SKILL.md 为链接，无法读取。")
        content = document.read_text(encoding="utf-8")
        detail = dict(path=reference, content=content, tools=[], mcp_servers=[], resources=[], error="")
        try:
            skill = load_node_skills([reference], skill_root=str(self.root))[0]
            detail.update(tools=list(skill.tools), mcp_servers=list(skill.mcp_servers),
                          resources=[resource.to_payload() for resource in skill.resources])
        except (SkillLoadError, RuntimeError, OSError, UnicodeError) as exc:
            detail["error"] = str(exc)
        return detail

    def category(self, reference: str) -> Path:
        path = self.resolve(reference, allow_root=True)
        if not path.is_dir():
            raise FileNotFoundError("目标文件夹不存在。")
        for ancestor in (path, *path.parents):
            if ancestor == self.root:
                break
            if (ancestor / "SKILL.md").exists():
                raise SkillCatalogError("Skill 是完整单元，不能把分类或其他 Skill 放进它的内部。")
        return path

    def bundle(self, reference: str) -> Path:
        path = self.resolve(reference)
        if not path.is_dir():
            raise FileNotFoundError("文件夹或 Skill 不存在。")
        parent = path.parent.relative_to(self.root).as_posix()
        self.category("" if parent == "." else parent)
        return path
