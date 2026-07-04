from __future__ import annotations

import base64
import json
import os
import threading
from datetime import datetime
from typing import Any

from src.file_transaction import atomic_write_text

from .domain_base import DomainBase
from .mobile_api import COMPANION_GRAPH_ID, COMPANION_NODE_ID
from .node_config_errors import NodeConfigReadError
from .node_config_service import node_config_service
from .node_desktop_pet_launcher import launch_node_desktop_pet_process
from .runtime_paths import _get_runtime_root
from .shared import HTTPException, envelope_text, normalize_envelope


SCHEMA_VERSION = 1


class NodeDesktopViewDomain(DomainBase):
    def __init__(self, core: object, *dependencies: object) -> None:
        super().__init__(core, *dependencies)
        object.__setattr__(self, "_lock", threading.Lock())

    def _store_path(self) -> str:
        return os.path.join(_get_runtime_root(), ".cache", "node_desktop_views.json")

    def _now(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _view_id(self, graph_id: str, node_id: str) -> str:
        raw = f"{graph_id}\0{node_id}".encode("utf-8")
        encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        return f"node_{encoded}"

    def _read_store_unlocked(self) -> dict[str, Any]:
        path = self._store_path()
        if not os.path.isfile(path):
            return {"schema_version": SCHEMA_VERSION, "views": []}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"node desktop view store contains invalid JSON: line {exc.lineno} column {exc.colno}: {exc.msg}",
            ) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to read node desktop view store: {exc}") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=500, detail="node desktop view store must be an object")
        views = payload.get("views")
        if views is None:
            views = []
        if not isinstance(views, list):
            raise HTTPException(status_code=500, detail="node desktop view store field 'views' must be a list")
        return {"schema_version": SCHEMA_VERSION, "views": [item for item in views if isinstance(item, dict)]}

    def _write_store_unlocked(self, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=500, detail="node desktop view store payload must be an object")
        path = self._store_path()
        try:
            atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to write node desktop view store: {exc}") from exc

    def _require_graph_id(self, value: object) -> str:
        safe_graph_id = self.graph_runtime._sanitize_graph_id(value)
        if not safe_graph_id:
            raise HTTPException(status_code=400, detail="graph_id is required")
        graphs = self.core.graph_api.list_graphs().get("graphs")
        if not isinstance(graphs, list):
            raise HTTPException(status_code=500, detail="invalid graph list response")
        if safe_graph_id == COMPANION_GRAPH_ID:
            return safe_graph_id
        if not any(isinstance(item, dict) and item.get("id") == safe_graph_id for item in graphs):
            raise HTTPException(status_code=404, detail="graph not found")
        return safe_graph_id

    def _require_node_id(self, graph_id: str, value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            raise HTTPException(status_code=400, detail="node_id is required")
        safe_node_id = self.graph_runtime._sanitize_node_id(raw)
        if graph_id == COMPANION_GRAPH_ID and safe_node_id == COMPANION_NODE_ID:
            config_path = self.core.mobile_api._companion_config_path()
            if not os.path.exists(config_path):
                raise HTTPException(status_code=404, detail="companion node not found")
            return safe_node_id
        try:
            resolved_node_id = self.graph_runtime._resolve_existing_node_id(graph_id, safe_node_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"node instance not found: {exc}") from exc
        config_path = self.graph_runtime._node_config_path(resolved_node_id, graph_id)
        if not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")
        return resolved_node_id

    def _node_config_path(self, graph_id: str, node_id: str) -> str:
        if graph_id == COMPANION_GRAPH_ID and node_id == COMPANION_NODE_ID:
            return self.core.mobile_api._companion_config_path()
        return self.graph_runtime._node_config_path(node_id, graph_id)

    def _read_node_snapshot(self, graph_id: str, node_id: str) -> dict[str, Any]:
        config_path = self._node_config_path(graph_id, node_id)
        if not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")
        try:
            cfg = node_config_service.read_strict(config_path)
        except NodeConfigReadError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {
            "id": node_id,
            "graph_id": graph_id,
            "name": str(cfg.get("name") or node_id),
            "type_id": str(cfg.get("type_id") or ""),
            "state": str(cfg.get("state") or "idle"),
            "pending_count": int(cfg.get("pending_count") or 0),
            "last_message": str(cfg.get("last_message") or ""),
            "last_run_at": cfg.get("last_run_at"),
            "last_runtime_event": cfg.get("last_runtime_event"),
            "runtime_tool_calls": cfg.get("runtime_tool_calls"),
            "input_num": cfg.get("input_num"),
            "output_num": cfg.get("output_num"),
            "working_path": str(cfg.get("working_path") or ""),
        }

    def _validate_working_path(self, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        path = os.path.normpath(os.path.abspath(os.path.expanduser(text)))
        if not os.path.isdir(path):
            raise HTTPException(status_code=400, detail=f"working_path directory does not exist: {path}")
        return path

    def _normalize_position(self, value: object) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise HTTPException(status_code=400, detail="position must be an object")
        display_id = str(value.get("display_id") or "").strip()
        try:
            x = int(value.get("x"))
            y = int(value.get("y"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="position.x and position.y must be integers") from exc
        result: dict[str, Any] = {"x": x, "y": y}
        if display_id:
            result["display_id"] = display_id
        return result

    def _normalize_bool(self, payload: dict[str, Any], key: str, default: bool) -> bool:
        value = payload.get(key)
        if value is None:
            return default
        if not isinstance(value, bool):
            raise HTTPException(status_code=400, detail=f"{key} must be boolean")
        return value

    def _normalize_avatar_style(self, value: object) -> str:
        if value is not None and not isinstance(value, str):
            raise HTTPException(status_code=400, detail="avatar_style must be string")
        avatar_style = str(value or "").strip()
        if not avatar_style:
            return ""
        self.core.pet_avatars.get_pet_avatar(avatar_style)
        return avatar_style

    def _attach_runtime_projection(self, view: dict[str, Any]) -> dict[str, Any]:
        graph_id = str(view.get("graph_id") or "").strip()
        node_id = str(view.get("node_id") or "").strip()
        projected = dict(view)
        projected["node"] = self._read_node_snapshot(graph_id, node_id)
        live = self.core.node_live_outputs.get(graph_id, node_id)
        projected["live"] = live if isinstance(live, dict) else {}
        return projected

    def _require_view_unlocked(self, store: dict[str, Any], view_id: str) -> dict[str, Any]:
        safe_view_id = str(view_id or "").strip()
        if not safe_view_id:
            raise HTTPException(status_code=400, detail="view_id is required")
        for item in store.get("views") or []:
            if isinstance(item, dict) and item.get("view_id") == safe_view_id:
                return item
        raise HTTPException(status_code=404, detail="node desktop view not found")

    def list_node_desktop_views(self):
        with self._lock:
            store = self._read_store_unlocked()
            views = [self._attach_runtime_projection(item) for item in store.get("views") or []]
        return {"schema_version": SCHEMA_VERSION, "views": views}

    def list_visible_desktop_pet_refs(self) -> list[dict[str, str]]:
        with self._lock:
            store = self._read_store_unlocked()
            refs: list[dict[str, str]] = []
            for item in store.get("views") or []:
                if not isinstance(item, dict) or not bool(item.get("visible")):
                    continue
                refs.append(
                    {
                        "view_id": str(item.get("view_id") or ""),
                        "graph_id": str(item.get("graph_id") or ""),
                        "node_id": str(item.get("node_id") or ""),
                        "avatar_style": str(item.get("avatar_style") or ""),
                    }
                )
        return refs

    def get_node_desktop_view(self, view_id: str):
        with self._lock:
            store = self._read_store_unlocked()
            view = self._require_view_unlocked(store, view_id)
            return {"view": self._attach_runtime_projection(view)}

    def upsert_node_desktop_view(self, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        graph_id = self._require_graph_id(payload.get("graph_id"))
        node_id = self._require_node_id(graph_id, payload.get("node_id"))
        position = self._normalize_position(payload.get("position"))
        now = self._now()
        view_id = self._view_id(graph_id, node_id)

        with self._lock:
            store = self._read_store_unlocked()
            views = store.get("views") or []
            existing = next(
                (item for item in views if isinstance(item, dict) and item.get("graph_id") == graph_id and item.get("node_id") == node_id),
                None,
            )
            if existing is None:
                existing = {
                    "view_id": view_id,
                    "graph_id": graph_id,
                    "node_id": node_id,
                    "created_at": now,
                }
                views.append(existing)
            existing["view_id"] = view_id
            existing["graph_id"] = graph_id
            existing["node_id"] = node_id
            existing["visible"] = self._normalize_bool(payload, "visible", True)
            existing["pinned"] = self._normalize_bool(payload, "pinned", False)
            if position is not None:
                existing["position"] = position
            if "avatar_style" in payload:
                existing["avatar_style"] = self._normalize_avatar_style(payload.get("avatar_style"))
            existing["updated_at"] = now
            existing["last_invoked_at"] = now
            store["views"] = views
            self._write_store_unlocked(store)
            view = self._attach_runtime_projection(existing)

        self.graph_runtime._log_graph_event(graph_id, "node_desktop_view_upserted", node_id=node_id, view_id=view_id)
        return {"ok": True, "view": view}

    def summon_node_desktop_view(self, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        working_path = self._validate_working_path(payload.get("working_path"))
        result = self.upsert_node_desktop_view(payload)
        if working_path:
            view = result.get("view") if isinstance(result, dict) else None
            graph_id = str((view or {}).get("graph_id") or "").strip()
            node_id = str((view or {}).get("node_id") or "").strip()
            config_path = self._node_config_path(graph_id, node_id)

            def mutate(next_cfg: dict[str, Any]) -> None:
                next_cfg["working_path"] = working_path

            node_config_service.update(config_path, mutate)
            self.graph_runtime._log_graph_event(
                graph_id,
                "node_desktop_view_summoned_here",
                node_id=node_id,
                view_id=str((view or {}).get("view_id") or ""),
                working_path=working_path,
            )
            return self.get_node_desktop_view(str((view or {}).get("view_id") or "")) | {"ok": True}
        return result

    def launch_node_desktop_pet(self, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        result = self.summon_node_desktop_view(payload)
        view = result.get("view") if isinstance(result, dict) else None
        if not isinstance(view, dict):
            raise HTTPException(status_code=500, detail="summon response is missing view")
        graph_id = str(view.get("graph_id") or "").strip()
        node_id = str(view.get("node_id") or "").strip()
        if not graph_id or not node_id:
            raise HTTPException(status_code=500, detail="summon response is missing graph_id or node_id")
        view_id = str(view.get("view_id") or "")
        print(f"[DesktopPet] launch graph_id={graph_id} node_id={node_id} view_id={view_id} pinned={bool(payload.get('pinned'))}")
        process = launch_node_desktop_pet_process(graph_id, node_id, payload | {"view_id": view_id})
        self.graph_runtime._log_graph_event(
            graph_id,
            "node_desktop_pet_launched",
            node_id=node_id,
            view_id=view_id,
            pid=process.pid,
        )
        return {"ok": True, "view": view, "pid": process.pid}

    def restore_visible_desktop_pets(self):
        with self._lock:
            store = self._read_store_unlocked()
            views = [dict(item) for item in store.get("views") or [] if isinstance(item, dict) and bool(item.get("visible"))]
        restored: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for view in views:
            view_id = str(view.get("view_id") or "").strip()
            graph_id = str(view.get("graph_id") or "").strip()
            node_id = str(view.get("node_id") or "").strip()
            try:
                graph_id = self._require_graph_id(graph_id)
                node_id = self._require_node_id(graph_id, node_id)
                print(f"[DesktopPet] restore launch graph_id={graph_id} node_id={node_id} view_id={view_id} pinned={bool(view.get('pinned'))}")
                process = launch_node_desktop_pet_process(graph_id, node_id, {"visible": True, "pinned": bool(view.get("pinned")), "view_id": view_id})
                restored.append({"view_id": view_id, "graph_id": graph_id, "node_id": node_id, "pid": process.pid})
                self.graph_runtime._log_graph_event(graph_id, "node_desktop_pet_restored", node_id=node_id, view_id=view_id, pid=process.pid)
            except Exception as exc:
                failed.append({"view_id": view_id, "graph_id": graph_id, "node_id": node_id, "error": str(getattr(exc, "detail", exc))})
        return {"requested": len(views), "restored": len(restored), "failed": failed, "views": restored}

    def mark_all_desktop_pets_hidden(self):
        now = self._now()
        changed: list[dict[str, str]] = []
        with self._lock:
            store = self._read_store_unlocked()
            for view in store.get("views") or []:
                if not isinstance(view, dict) or not bool(view.get("visible")):
                    continue
                view["visible"] = False
                view["updated_at"] = now
                changed.append(
                    {
                        "view_id": str(view.get("view_id") or ""),
                        "graph_id": str(view.get("graph_id") or ""),
                        "node_id": str(view.get("node_id") or ""),
                    }
                )
            if changed:
                self._write_store_unlocked(store)
        return {"updated": len(changed), "views": changed}

    def update_node_desktop_view(self, view_id: str, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        position_supplied = "position" in payload
        position = self._normalize_position(payload.get("position")) if position_supplied else None
        now = self._now()
        with self._lock:
            store = self._read_store_unlocked()
            view = self._require_view_unlocked(store, view_id)
            if "visible" in payload:
                view["visible"] = self._normalize_bool(payload, "visible", bool(view.get("visible", True)))
            if "pinned" in payload:
                view["pinned"] = self._normalize_bool(payload, "pinned", bool(view.get("pinned", False)))
            if position_supplied:
                if position is None:
                    view.pop("position", None)
                else:
                    view["position"] = position
            if "avatar_style" in payload:
                view["avatar_style"] = self._normalize_avatar_style(payload.get("avatar_style"))
            view["updated_at"] = now
            self._write_store_unlocked(store)
            projected = self._attach_runtime_projection(view)
        self.graph_runtime._log_graph_event(
            str(projected.get("graph_id") or ""),
            "node_desktop_view_updated",
            node_id=str(projected.get("node_id") or ""),
            view_id=str(projected.get("view_id") or ""),
        )
        return {"ok": True, "view": projected}

    def delete_node_desktop_view(self, view_id: str):
        with self._lock:
            store = self._read_store_unlocked()
            view = self._require_view_unlocked(store, view_id)
            graph_id = str(view.get("graph_id") or "").strip()
            node_id = str(view.get("node_id") or "").strip()
            store["views"] = [item for item in store.get("views") or [] if not isinstance(item, dict) or item.get("view_id") != view_id]
            self._write_store_unlocked(store)
        self.graph_runtime._log_graph_event(graph_id, "node_desktop_view_deleted", node_id=node_id, view_id=view_id)
        return {"ok": True, "view_id": view_id, "graph_id": graph_id, "node_id": node_id}

    def send_node_desktop_view_message(self, view_id: str, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        with self._lock:
            store = self._read_store_unlocked()
            view = dict(self._require_view_unlocked(store, view_id))
        message = payload.get("payload")
        if message is None:
            message = payload.get("message")
        if message is None:
            raise HTTPException(status_code=400, detail="message is required")
        normalized = normalize_envelope(message, default_role="user")
        if not envelope_text(normalized).strip():
            raise HTTPException(status_code=400, detail="message text is required")
        graph_id = str(view.get("graph_id") or "").strip()
        node_id = str(view.get("node_id") or "").strip()
        result = self.core.mobile_api.send_mobile_node_message(
            "local",
            graph_id,
            node_id,
            {"payload": normalized, "trace_id": payload.get("trace_id")},
        )
        self.graph_runtime._log_graph_event(
            graph_id,
            "node_desktop_view_message_sent",
            node_id=node_id,
            view_id=view_id,
            trace_id=result.get("trace_id") if isinstance(result, dict) else None,
        )
        return result | {"view_id": view_id}


__all__ = ["NodeDesktopViewDomain"]
