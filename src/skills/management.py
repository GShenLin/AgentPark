"""Whole-bundle filesystem operations with a recoverable project trash area."""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

from src.capabilities.discovery_cache import invalidate_discovery_cache
from src.file_transaction import atomic_write_text
from src.skills.catalog import SkillCatalog, SkillCatalogError, is_link
from src.skills.roots import root_id


class SkillManager:
    def __init__(self, root: Path):
        self.catalog = SkillCatalog(root)
        self.lock = threading.RLock()
        self.trash = root.parent / ".skill-trash" / root_id(root)

    def changed(self) -> None:
        invalidate_discovery_cache("skills", str(self.catalog.root))

    def create_folder(self, parent: str, name: str) -> None:
        if "/" in name or "\\" in name:
            raise SkillCatalogError("请输入单层文件夹名称；可进入文件夹后继续创建子文件夹。")
        if not self.catalog.root.exists() and not parent:
            self.catalog.resolve("", allow_root=True).mkdir(parents=True)
        self.catalog.category(parent)
        target = self.catalog.resolve(f"{parent}/{name}" if parent else name)
        target.mkdir()
        self.changed()

    def move(self, source: str, parent: str, name: str) -> None:
        path = self.catalog.bundle(source)
        self.catalog.category(parent)
        if "/" in name or "\\" in name:
            raise SkillCatalogError("名称不能包含路径分隔符。")
        target = self.catalog.resolve(f"{parent}/{name}" if parent else name)
        if target == path or target.is_relative_to(path):
            raise SkillCatalogError("目标不能是自身或自己的子目录。")
        if target.exists():
            raise FileExistsError("目标已有同名目录，不会覆盖或合并。")
        path.rename(target)
        self.changed()

    def delete(self, source: str) -> str:
        path = self.catalog.bundle(source)
        self._check_trash()
        identifier = uuid.uuid4().hex
        record = self.trash / identifier
        record.mkdir(parents=True)
        atomic_write_text(str(record / "record.json"), json.dumps({"path": source}, ensure_ascii=False))
        try:
            path.rename(record / "bundle")
        except OSError:
            (record / "record.json").unlink()
            record.rmdir()
            raise
        self.changed()
        return identifier

    def _check_trash(self) -> None:
        self.catalog.resolve("", allow_root=True)
        if is_link(self.trash) or is_link(self.trash.parent):
            raise SkillCatalogError("回收区不能是链接目录。")

    def deleted(self) -> list[dict]:
        self._check_trash()
        if not self.trash.exists():
            return []
        result = []
        for record in sorted(self.trash.iterdir()):
            if not record.is_dir() or is_link(record):
                raise SkillCatalogError("回收区包含无效记录。")
            metadata = record / "record.json"
            if is_link(metadata) or is_link(record / "bundle"):
                raise SkillCatalogError("回收记录不能是链接。")
            data = json.loads(metadata.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("path"), str):
                raise SkillCatalogError("回收记录格式错误。")
            result.append(dict(id=record.name, path=data["path"]))
        return result

    def restore(self, identifier: str) -> None:
        record_info = next((item for item in self.deleted() if item["id"] == identifier), None)
        if record_info is None:
            raise FileNotFoundError("回收记录不存在。")
        target = self.catalog.resolve(record_info["path"])
        parent = target.parent.relative_to(self.catalog.root).as_posix()
        self.catalog.category("" if parent == "." else parent)
        if target.exists():
            raise FileExistsError("原位置已有同名目录，请先移动该目录。")
        record = self.trash / identifier
        (record / "bundle").rename(target)
        (record / "record.json").unlink()
        record.rmdir()
        self.changed()
