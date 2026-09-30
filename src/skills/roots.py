"""One ordered root registry shared by runtime discovery and the settings catalog."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from threading import RLock

from src.capabilities.discovery_cache import invalidate_discovery_cache
from src.file_transaction import atomic_write_text
from src.workspace_settings import get_workspace_root


ROOT_SETTINGS_LOCK = RLock()


def root_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def root_id(path: Path) -> str:
    return hashlib.sha256(root_key(path).encode("utf-8")).hexdigest()[:20]


class SkillRootStore:
    def __init__(self, workspace: Path, project: Path, user: Path | None):
        self.project = project.absolute()
        self.user = user.absolute() if user is not None else None
        self.config_path = workspace / ".cache" / "skill-roots.json"

    def custom_paths(self) -> list[Path]:
        if not self.config_path.exists():
            return []
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or set(payload) != {"paths"} or not isinstance(payload["paths"], list):
            raise ValueError(f"Skill 加载路径配置格式错误：{self.config_path}")
        result = []
        for value in payload["paths"]:
            if not isinstance(value, str) or not value.strip() or not Path(value).is_absolute():
                raise ValueError("Skill 加载路径必须是非空的绝对路径。")
            result.append(Path(value))
        return result

    def sources(self) -> list[dict]:
        roots = [(self.project, "project", "当前项目")]
        if self.user is not None:
            roots.append((self.user, "user", "用户 Skills"))
        roots.extend((path, "custom", f"自定义 · {path.name}") for path in self.custom_paths())
        result = []
        seen = set()
        for path, kind, label in roots:
            key = root_key(path)
            if key in seen:
                continue
            seen.add(key)
            result.append(dict(id=root_id(path), path=str(path), kind=kind, label=label))
        return result

    def add(self, value: str) -> None:
        raw = Path(value.strip()).expanduser()
        if not value.strip() or not raw.is_absolute():
            raise ValueError("请输入 Skill 根文件夹的绝对路径。")
        path = raw.resolve()
        if not path.is_dir():
            raise ValueError("该路径不存在或不是文件夹；请输入运行 AgentPark 的设备上的路径。")
        if (path / "SKILL.md").exists():
            raise ValueError("请选择包含多个 Skill 文件夹的上级目录，不是单个 Skill 文件夹。")
        with ROOT_SETTINGS_LOCK:
            for source in self.sources():
                existing = Path(source["path"]).resolve()
                if path == existing or path.is_relative_to(existing) or existing.is_relative_to(path):
                    raise ValueError(f"该路径与现有加载路径重复或嵌套：{existing}")
            self._save([*self.custom_paths(), path])

    def remove(self, identifier: str) -> None:
        with ROOT_SETTINGS_LOCK:
            source = next((item for item in self.sources() if item["id"] == identifier), None)
            if source is None:
                raise ValueError("加载路径不存在。")
            if source["kind"] != "custom":
                raise ValueError("项目和用户目录是默认加载来源，不能移除。")
            self._save([path for path in self.custom_paths() if root_id(path) != identifier])

    def _save(self, paths: list[Path]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(str(self.config_path), json.dumps({"paths": [str(path) for path in paths]}, ensure_ascii=False, indent=2) + "\n")
        invalidate_discovery_cache("skills")


def configured_skill_roots(project: str, user: str) -> tuple[str, ...]:
    store = SkillRootStore(Path(get_workspace_root()), Path(project), Path(user))
    return tuple(source["path"] for source in store.sources())
