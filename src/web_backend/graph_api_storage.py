from __future__ import annotations

import json
import os
import shutil
import threading
import time
from datetime import datetime

from src.file_transaction import atomic_write_text
from ..workspace_settings import read_startup_graph_settings, save_startup_graph_settings

from .graph_runtime_registry import GraphConfigReadError
from .graph_output_routes import normalize_output_routes
from . import runtime_paths
from .node_deletion import NodeDeletionBlocked, delete_node_directory
from .service_host import HostBoundService
from .shared import HTTPException

PROTECTED_GRAPH_IDS = {"default", "companion"}


def _is_protected_graph_id(graph_id: object) -> bool:
    return str(graph_id or "").strip().lower() in PROTECTED_GRAPH_IDS


def _graph_config_version(config_path: str) -> int:
    try:
        return int(os.stat(config_path).st_mtime_ns)
    except OSError:
        return 0


def _write_graph_config(config_path: str, payload: dict) -> None:
    if not isinstance(payload, dict):
        raise ValueError("graph config payload must be an object")
    atomic_write_text(config_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _read_graph_config_file(config_path: str) -> dict:
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except json.JSONDecodeError as exc:
        raise GraphConfigReadError(
            f"graph config contains invalid JSON: {config_path}: line {exc.lineno} column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise GraphConfigReadError(
            f"failed to read graph config {config_path}: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise GraphConfigReadError(f"graph config must be a JSON object: {config_path}")
    return payload


class GraphApiStorage(HostBoundService):
    def _sanitize_graph_payload_for_storage(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            return {}
        graph = dict(payload)
        valid_node_ids = self._graph_node_ids_for_route_validation(graph)
        try:
            graph["output_routes"] = normalize_output_routes(graph.get("output_routes"), valid_node_ids=valid_node_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        graph["working_path"] = str(graph.get("working_path") or "").strip()
        graph.pop("nodes", None)
        graph.pop("links", None)
        return graph

    def _graph_node_ids_for_route_validation(self, graph: dict) -> set[str] | None:
        node_ids: set[str] = set()
        nodes = graph.get("nodes")
        if isinstance(nodes, list):
            for item in nodes:
                if isinstance(item, dict):
                    node_id = str(item.get("id") or "").strip()
                    if node_id:
                        node_ids.add(node_id)
        graph_id = self.graph_runtime._sanitize_graph_id(graph.get("id") or self.default_graph_id)
        graph_dir = self.graph_runtime._graph_dir(graph_id)
        if graph_dir and os.path.isdir(graph_dir):
            for entry in os.listdir(graph_dir):
                if entry == "agents":
                    continue
                config_path = os.path.join(graph_dir, entry, "config.json")
                if os.path.exists(config_path):
                    node_ids.add(entry)
        return node_ids or None

    def list_graphs(self):
        graphs_dir = runtime_paths._get_graphs_dir()
        graphs = []
        if not os.path.isdir(graphs_dir):
            graphs.append({"id": "default", "name": "default", "updated_at": None, "readonly": True})
            return {"graphs": graphs}

        default_config = os.path.join(graphs_dir, "default", "config.json")
        default_updated = None
        default_name = "default"
        if os.path.exists(default_config):
            try:
                default_updated = datetime.fromtimestamp(os.path.getmtime(default_config)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                default_updated = None
            try:
                payload = _read_graph_config_file(default_config)
            except GraphConfigReadError as exc:
                raise HTTPException(status_code=500, detail=str(exc))
            if payload.get("name"):
                default_name = str(payload.get("name"))
        graphs.append({"id": "default", "name": default_name, "updated_at": default_updated, "readonly": True})

        for entry in os.listdir(graphs_dir):
            if entry in {"agents", "default"}:
                continue
            graph_dir = os.path.join(graphs_dir, entry)
            if not os.path.isdir(graph_dir):
                continue
            config_path = os.path.join(graph_dir, "config.json")
            if not os.path.exists(config_path):
                continue
            name = entry
            try:
                payload = _read_graph_config_file(config_path)
            except GraphConfigReadError as exc:
                raise HTTPException(status_code=500, detail=str(exc))
            if payload.get("name"):
                name = str(payload.get("name"))
            updated_at = None
            try:
                updated_at = datetime.fromtimestamp(os.path.getmtime(config_path)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                updated_at = None
            graphs.append({
                "id": entry,
                "name": name,
                "updated_at": updated_at,
                "readonly": _is_protected_graph_id(entry),
            })
        graphs.sort(key=lambda item: item["name"].lower())
        return {"graphs": graphs}

    def get_graph(self, graph_id: str, if_version: int = 0):
        safe_id = self.graph_runtime._sanitize_graph_id(graph_id)
        if not safe_id:
            raise HTTPException(status_code=400, detail="invalid graph id")
        self.graph_runtime._log_graph_event(safe_id, "graph_load_api")
        graphs_dir = runtime_paths._get_graphs_dir()
        config_path = os.path.join(graphs_dir, safe_id, "config.json")
        if not os.path.exists(config_path):
            if safe_id == "default":
                return {"graph": {"id": "default", "name": "default", "output_routes": {}, "version": 0}}
            raise HTTPException(status_code=404, detail="graph not found")
        try:
            version = _graph_config_version(config_path)
            try:
                requested_version = int(if_version or 0)
            except Exception:
                requested_version = 0
            if requested_version > 0 and version <= requested_version:
                return {"graph": {"id": safe_id, "version": version, "unchanged": True}}
            payload = _read_graph_config_file(config_path)
            cleaned = self._sanitize_graph_payload_for_storage(payload)
            if cleaned != payload:
                _write_graph_config(config_path, cleaned)
                version = _graph_config_version(config_path)
            cleaned["version"] = version
            return {"graph": cleaned}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    def save_graph(self, graph_id: str, payload: dict):
        graph = (payload or {}).get("graph")
        safe_id = self.graph_runtime._sanitize_graph_id(graph_id)
        if not safe_id:
            raise HTTPException(status_code=400, detail="invalid graph id")
        if not isinstance(graph, dict):
            raise HTTPException(status_code=400, detail="graph is required")

        save_reason = str((payload or {}).get("save_reason") or "").strip()
        raw_source_graph_id = graph.get("source_graph_id")
        if raw_source_graph_id is None:
            raw_source_graph_id = (payload or {}).get("source_graph_id")
        source_graph_id = ""
        if str(raw_source_graph_id or "").strip():
            source_graph_id = self.graph_runtime._sanitize_graph_id(raw_source_graph_id)
        self.graph_runtime._log_graph_event(
            safe_id,
            "graph_save_api",
            source_graph_id=source_graph_id,
            save_reason=save_reason,
            nodes_count=len(graph.get("nodes") or []) if isinstance(graph.get("nodes"), list) else None,
            output_routes_count=len(graph.get("output_routes") or {}) if isinstance(graph.get("output_routes"), dict) else None,
        )

        graphs_dir = runtime_paths._get_graphs_dir()
        os.makedirs(graphs_dir, exist_ok=True)
        graph_dir = os.path.join(graphs_dir, safe_id)
        os.makedirs(graph_dir, exist_ok=True)
        config_path = os.path.join(graph_dir, "config.json")
        graph = dict(graph)
        graph.pop("source_graph_id", None)
        graph = self._sanitize_graph_payload_for_storage(graph)
        graph["id"] = safe_id
        if not graph.get("name"):
            graph["name"] = safe_id
        if source_graph_id and source_graph_id != safe_id:
            self._copy_graph_artifacts(source_graph_id, graph_dir, safe_id)
        try:
            _write_graph_config(config_path, graph)
            if source_graph_id and source_graph_id != safe_id:
                self.graph_runtime._register_all_scheduled_nodes(force_rebuild=True)
            updated_at = datetime.fromtimestamp(os.path.getmtime(config_path)).strftime("%Y-%m-%d %H:%M:%S")
            return {"graph": {"id": safe_id, "name": graph.get("name"), "updated_at": updated_at}}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    def _copy_graph_artifacts(self, source_graph_id: str, graph_dir: str, target_graph_id: str) -> None:
        source_dir = os.path.join(runtime_paths._get_graphs_dir(), source_graph_id)
        if not os.path.isdir(source_dir):
            return
        for entry in os.listdir(source_dir):
            if entry in {"config.json", "runner.events.jsonl", "runtime.events.jsonl"}:
                continue
            src_path = os.path.join(source_dir, entry)
            dst_path = os.path.join(graph_dir, entry)
            try:
                if os.path.isdir(src_path):
                    if os.path.exists(dst_path):
                        shutil.rmtree(dst_path)
                    shutil.copytree(src_path, dst_path)
                    self._retarget_copied_node_config(dst_path, entry, target_graph_id)
                elif os.path.isfile(src_path):
                    shutil.copy2(src_path, dst_path)
            except Exception:
                pass

    def _retarget_copied_node_config(self, node_dir: str, node_id: str, target_graph_id: str) -> None:
        config_path = os.path.join(node_dir, "config.json")
        if not os.path.exists(config_path):
            return
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                return
            payload["node_id"] = str(node_id)
            payload["graph_id"] = str(target_graph_id)
            _write_graph_config(config_path, payload)
        except Exception:
            pass

    def delete_graph(self, graph_id: str, wait_timeout_seconds: float = 10.0):
        safe_id = self.graph_runtime._sanitize_graph_id(graph_id)
        if not safe_id:
            raise HTTPException(status_code=400, detail="invalid graph id")
        if _is_protected_graph_id(safe_id):
            raise HTTPException(status_code=403, detail=f"protected graph cannot be deleted: {safe_id}")
        self.graph_runtime._unregister_scheduled_graph(safe_id)

        graphs_dir = os.path.abspath(runtime_paths._get_graphs_dir())
        graph_dir = os.path.abspath(os.path.join(graphs_dir, safe_id))
        try:
            common = os.path.commonpath([graphs_dir, graph_dir])
        except Exception:
            common = ""
        if common != graphs_dir or graph_dir == graphs_dir:
            raise HTTPException(status_code=400, detail="invalid graph path")

        self._stop_graph_runner_for_delete(safe_id, wait_timeout_seconds)

        deleted = False
        if os.path.exists(graph_dir):
            if not os.path.isdir(graph_dir):
                raise HTTPException(status_code=400, detail="graph path is not a directory")
            try:
                self._delete_graph_node_directories(safe_id, graph_dir, wait_timeout_seconds)
                shutil.rmtree(graph_dir)
                deleted = True
            except NodeDeletionBlocked as exc:
                raise HTTPException(status_code=409, detail=f"graph deletion is blocked: {str(exc)}")
            except Exception as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        self._reset_startup_graph_after_delete(safe_id)
        return {"ok": True, "graph_id": safe_id, "deleted": deleted}

    def _reset_startup_graph_after_delete(self, deleted_graph_id: str) -> None:
        try:
            startup = read_startup_graph_settings()
            startup_graph_id = self.graph_runtime._sanitize_graph_id(startup.get("graph_id"))
            if startup_graph_id != deleted_graph_id:
                return
            save_startup_graph_settings(self.default_graph_id, self.default_graph_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to reset startup graph after delete: {exc}") from exc

    def _stop_graph_runner_for_delete(self, graph_id: str, wait_timeout_seconds: float) -> None:
        safe_id = self.graph_runtime._sanitize_graph_id(graph_id)
        with self.graph_runners_lock:
            existing = self.graph_runners.get(safe_id)
            stop_event = self.graph_runtime._runner_stop_event(existing)
            wake_event = self.graph_runtime._runner_wake_signal(existing)

        if isinstance(stop_event, threading.Event):
            stop_event.set()
        if hasattr(wake_event, "set"):
            wake_event.set()

        deadline = max(0.0, float(wait_timeout_seconds or 0.0))
        stop_at = time.monotonic() + deadline
        while True:
            threads = self.graph_runtime._runner_threads(existing)
            live_threads = [
                thread for thread in threads if isinstance(thread, threading.Thread) and thread.is_alive()
            ]
            if not live_threads:
                break
            for thread in live_threads:
                remaining = max(0.0, stop_at - time.monotonic()) if deadline > 0 else 0.0
                thread.join(timeout=remaining)
            if any(thread.is_alive() for thread in live_threads):
                raise HTTPException(status_code=409, detail="graph deletion is blocked: graph runner did not stop")
        with self.graph_runners_lock:
            if self.graph_runners.get(safe_id) is existing:
                self.graph_runners.pop(safe_id, None)

    def _delete_graph_node_directories(self, graph_id: str, graph_dir: str, wait_timeout_seconds: float) -> None:
        memory_root = os.path.join(runtime_paths._get_runtime_root(), "memories")
        for entry in sorted(os.listdir(graph_dir)):
            node_dir = os.path.join(graph_dir, entry)
            if not os.path.isdir(node_dir):
                continue
            config_path = os.path.join(node_dir, "config.json")
            if not os.path.exists(config_path):
                continue
            delete_node_directory(
                core=self.core,
                graph_runtime=self.graph_runtime,
                graph_id=graph_id,
                node_id=entry,
                node_dir=node_dir,
                memory_root=memory_root,
                wait_timeout_seconds=wait_timeout_seconds,
            )


__all__ = ["GraphApiStorage"]
