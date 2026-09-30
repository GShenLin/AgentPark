from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, StrictStr

from nodes.agent_skill_loader import default_skill_root, user_skill_root
from src.skills.catalog import SkillCatalogError
from src.skills.management import SkillManager
from src.skills.references import references_under, skill_references
from src.skills.roots import SkillRootStore
from src.workspace_settings import get_workspace_root
from . import runtime_paths


class SkillOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["create_folder", "move", "delete", "restore"]
    root_id: StrictStr
    path: StrictStr = ""
    parent: StrictStr = ""
    name: StrictStr = ""
    trash_id: StrictStr = ""


class SkillRootOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["add", "remove"]
    path: StrictStr = ""
    root_id: StrictStr = ""


class SkillsApi:
    def __init__(self, root: Path | None = None, workspace: Path | None = None,
                 memories: Path | None = None, user_root: Path | None = None):
        self.workspace = workspace or Path(get_workspace_root())
        self.memories = memories
        self.roots = SkillRootStore(self.workspace, root or Path(default_skill_root()),
                                   user_root if root is not None else Path(user_skill_root()))
        self.lock = RLock()
        self.managers: dict[str, SkillManager] = {}

    def _manager(self, identifier: str) -> SkillManager:
        source = next((item for item in self.roots.sources() if item["id"] == identifier), None)
        if source is None:
            raise HTTPException(404, "加载来源不存在，请刷新 Skill 列表。")
        if identifier not in self.managers:
            self.managers[identifier] = SkillManager(Path(source["path"]))
        return self.managers[identifier]

    def _references(self) -> dict[str, list[str]]:
        return skill_references(self.workspace, self.memories or Path(runtime_paths._get_graphs_dir()))

    def list_skills(self):
        try:
            with self.lock:
                usage_error = ""
                try:
                    references = self._references()
                except (ValueError, OSError) as exc:
                    references = {}
                    usage_error = str(exc)
                sources = self.roots.sources()
                for index, source in enumerate(sources):
                    manager = self._manager(source["id"])
                    source.update(entries=[], trash=[], error="", exists=manager.catalog.root.is_dir())
                    try:
                        source["entries"] = manager.catalog.entries()
                        source["trash"] = manager.deleted()
                        for entry in source["entries"]:
                            entry["root_id"] = source["id"]
                            entry["used_by"] = references_under(references, entry["path"])
                            entry["shadowed_by"] = next((higher["label"] for higher in sources[:index]
                                if (Path(higher["path"]) / entry["path"]).exists()), "") if entry["kind"] == "skill" else ""
                    except (ValueError, OSError) as exc:
                        source["error"] = str(exc)
                return {"sources": sources, "usage_error": usage_error}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    def detail(self, root_id: str, path: str):
        try:
            with self.lock:
                return self._manager(root_id).catalog.detail(path)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    def operate(self, payload: SkillOperation):
        try:
            with self.lock:
                manager = self._manager(payload.root_id)
                if payload.action in {"move", "delete"}:
                    manager.catalog.bundle(payload.path)
                    used_by = references_under(self._references(), payload.path)
                    if used_by:
                        raise HTTPException(409, "请先在以下节点或模板中取消 Skill 引用，再整理或删除：\n" + "\n".join(used_by))
                if payload.action == "create_folder":
                    manager.create_folder(payload.parent, payload.name)
                elif payload.action == "move":
                    manager.move(payload.path, payload.parent, payload.name)
                elif payload.action == "delete":
                    manager.delete(payload.path)
                else:
                    manager.restore(payload.trash_id)
                return {"ok": True}
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (SkillCatalogError, ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc

    def configure_roots(self, payload: SkillRootOperation):
        try:
            with self.lock:
                if payload.action == "add":
                    self.roots.add(payload.path)
                else:
                    manager = self._manager(payload.root_id)
                    references = self._references()
                    locations = sorted({location for entry in manager.catalog.entries()
                                        for location in references_under(references, entry["path"])})
                    if locations:
                        raise HTTPException(409, "请先取消以下节点或模板的 Skill 引用再移除加载路径：\n" + "\n".join(locations))
                    self.roots.remove(payload.root_id)
                return {"ok": True}
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
