import json
import os
import shutil
import subprocess
from types import SimpleNamespace

from src.providers.agent_environment_context import resolve_agent_configured_working_path

from . import runtime_paths
from .node_config_errors import NodeConfigWriteError
from .node_config_errors import NodeConfigReadError
from .node_config_service import RUNTIME_STATE_FIELDS, node_config_service, node_runtime_state_version
from .node_instance_artifacts import rename_node_artifacts
from .node_instance_artifacts import rename_node_references_in_graph
from .node_metadata_reader import NodeMetadataError
from .node_memory_store import NodeMemoryPersistenceError, clear_node_memory
from .node_runtime_projection import load_node_runtime_projection
from .node_event_sequence import bump_node_event_seq
from .node_state_machine import parse_node_state
from .runtime_state_memory_store import runtime_state_memory_store
from .service_host import HostBoundService
from .shared import (
    HTTPException,
    _read_json_dict,
    _write_json_dict,
)


def _config_file_version(config_path: str) -> int:
    version = 0
    try:
        version = max(version, int(os.stat(config_path).st_mtime_ns))
    except OSError:
        pass
    version = max(version, node_runtime_state_version(config_path))
    return version


class NodeInstanceRegistry(HostBoundService):
    def create_node_instance(self, payload: dict):
        node_id = (payload or {}).get("node_id")
        type_id = (payload or {}).get("type_id")
        name = (payload or {}).get("name")
        graph_id = (payload or {}).get("graph_id")
        ui = (payload or {}).get("ui")
        if not isinstance(node_id, str) or not node_id.strip():
            raise HTTPException(status_code=400, detail="node_id is required")
        if not isinstance(type_id, str) or not type_id.strip():
            raise HTTPException(status_code=400, detail="type_id is required")
        if ui is not None and not isinstance(ui, dict):
            raise HTTPException(status_code=400, detail="ui must be object")

        graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_id = self.graph_runtime._sanitize_node_id(node_id)
        node_dir = self.graph_runtime._node_dir(graph_id, safe_id)
        try:
            os.makedirs(node_dir, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        try:
            self.graph_runtime._ensure_node_memory_file(safe_id, graph_id)
        except NodeMemoryPersistenceError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        try:
            config_path = self.graph_runtime._write_node_config(
                safe_id,
                type_id,
                name=name if isinstance(name, str) else None,
                graph_id=graph_id,
                ui=ui if isinstance(ui, dict) else None,
            )
        except NodeConfigWriteError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        if not config_path:
            raise HTTPException(status_code=500, detail="failed to write node config")
        cfg = _read_json_dict(config_path)
        if isinstance(cfg, dict) and cfg:
            before = json.dumps(cfg, ensure_ascii=False, sort_keys=True)
            try:
                self.graph_runtime._try_init_node_config(type_id, cfg, graph_id, safe_id)
            except NodeMetadataError as exc:
                raise HTTPException(status_code=500, detail=str(exc))
            after = json.dumps(cfg, ensure_ascii=False, sort_keys=True)
            if after != before:
                _write_json_dict(config_path, cfg)
        self.graph_runtime._refresh_scheduled_node(graph_id, safe_id)
        return {"ok": True, "node_id": safe_id, "type_id": type_id, "graph_id": graph_id, "config_path": config_path}

    def rename_node_instance(self, node_id: str, payload: dict, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        new_node_id_raw = payload.get("new_node_id")
        new_name_raw = payload.get("new_name")
        if not isinstance(new_node_id_raw, str) or not new_node_id_raw.strip():
            raise HTTPException(status_code=400, detail="new_node_id is required")
        if new_name_raw is not None and not isinstance(new_name_raw, str):
            raise HTTPException(status_code=400, detail="new_name must be string")

        safe_new_node_id = self.graph_runtime._sanitize_node_id(new_node_id_raw)
        old_dir = self.graph_runtime._node_dir(safe_graph_id, safe_node_id)
        old_config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        if not safe_new_node_id:
            raise HTTPException(status_code=400, detail="invalid new_node_id")
        if not old_config_path or not os.path.exists(old_config_path) or not os.path.isdir(old_dir):
            raise HTTPException(status_code=404, detail="node instance not found")

        new_dir = self.graph_runtime._node_dir(safe_graph_id, safe_new_node_id)
        if safe_new_node_id != safe_node_id and os.path.exists(new_dir):
            raise HTTPException(status_code=409, detail="target node id already exists")

        try:
            cfg = node_config_service.read_strict(old_config_path)
        except NodeConfigReadError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        type_id = str(cfg.get("type_id") or "").strip()

        self.graph_runtime._unregister_scheduled_node(safe_graph_id, safe_node_id)
        try:
            if safe_new_node_id != safe_node_id:
                os.rename(old_dir, new_dir)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to rename node directory: {str(e)}")

        config_path = self.graph_runtime._node_config_path(safe_new_node_id, safe_graph_id)
        runtime_state_memory_store.rename(old_config_path, config_path)
        try:
            next_cfg = node_config_service.read_strict(config_path)
        except NodeConfigReadError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        next_cfg["node_id"] = safe_new_node_id
        next_cfg["graph_id"] = safe_graph_id
        next_cfg["name"] = (
            new_name_raw.strip()
            if isinstance(new_name_raw, str) and new_name_raw.strip()
            else safe_new_node_id
        )
        if not _write_json_dict(config_path, next_cfg):
            raise HTTPException(status_code=500, detail="failed to update node config")

        if safe_new_node_id != safe_node_id and os.path.isdir(new_dir):
            rename_node_artifacts(new_dir, safe_node_id, safe_new_node_id)

        rename_node_references_in_graph(self.graph_runtime, safe_graph_id, safe_node_id, safe_new_node_id, new_name_raw)
        self.graph_runtime._refresh_scheduled_node(safe_graph_id, safe_new_node_id)

        self.graph_runtime._log_graph_event(
            safe_graph_id,
            "node_renamed",
            old_node_id=safe_node_id,
            new_node_id=safe_new_node_id,
            node_type_id=type_id or None,
        )
        return {
            "ok": True,
            "old_node_id": safe_node_id,
            "node_id": safe_new_node_id,
            "graph_id": safe_graph_id,
            "type_id": type_id,
            "config_path": config_path,
        }

    def clone_node_instance(self, node_id: str, payload: dict, graph_id: str = ""):
        safe_source_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        new_node_id_raw = payload.get("new_node_id")
        new_name_raw = payload.get("new_name")
        ui_raw = payload.get("ui")
        target_graph_id_raw = payload.get("target_graph_id")
        if not isinstance(new_node_id_raw, str) or not new_node_id_raw.strip():
            raise HTTPException(status_code=400, detail="new_node_id is required")
        if new_name_raw is not None and not isinstance(new_name_raw, str):
            raise HTTPException(status_code=400, detail="new_name must be string")
        if ui_raw is not None and not isinstance(ui_raw, dict):
            raise HTTPException(status_code=400, detail="ui must be object")
        if target_graph_id_raw is not None and not isinstance(target_graph_id_raw, str):
            raise HTTPException(status_code=400, detail="target_graph_id must be string")

        safe_target_graph_id = (
            self.graph_runtime._sanitize_graph_id(target_graph_id_raw)
            if isinstance(target_graph_id_raw, str) and target_graph_id_raw.strip()
            else safe_source_graph_id
        )

        safe_new_node_id = self.graph_runtime._sanitize_node_id(new_node_id_raw)
        if not safe_new_node_id:
            raise HTTPException(status_code=400, detail="invalid new_node_id")
        if safe_target_graph_id == safe_source_graph_id and safe_new_node_id == safe_node_id:
            raise HTTPException(status_code=409, detail="target node id already exists")

        old_dir = self.graph_runtime._node_dir(safe_source_graph_id, safe_node_id)
        old_config_path = self.graph_runtime._node_config_path(safe_node_id, safe_source_graph_id)
        if not old_config_path or not os.path.exists(old_config_path) or not os.path.isdir(old_dir):
            raise HTTPException(status_code=404, detail="node instance not found")

        new_dir = self.graph_runtime._node_dir(safe_target_graph_id, safe_new_node_id)
        if os.path.exists(new_dir):
            raise HTTPException(status_code=409, detail="target node id already exists")

        memory_root = os.path.join(runtime_paths._get_runtime_root(), "memories")
        if not self.graph_runtime._is_safe_subdir(memory_root, old_dir) or not self.graph_runtime._is_safe_subdir(memory_root, new_dir):
            raise HTTPException(status_code=400, detail="invalid node path")

        try:
            source_cfg = node_config_service.read_strict(old_config_path)
        except NodeConfigReadError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        type_id = str(source_cfg.get("type_id") or "").strip()

        try:
            shutil.copytree(old_dir, new_dir)
            rename_node_artifacts(new_dir, safe_node_id, safe_new_node_id)

            config_path = self.graph_runtime._node_config_path(safe_new_node_id, safe_target_graph_id)
            next_cfg = node_config_service.read_strict(config_path)
            next_cfg["node_id"] = safe_new_node_id
            next_cfg["graph_id"] = safe_target_graph_id
            next_cfg["name"] = (
                new_name_raw.strip()
                if isinstance(new_name_raw, str) and new_name_raw.strip()
                else str(source_cfg.get("name") or safe_new_node_id).strip() or safe_new_node_id
            )
            if isinstance(ui_raw, dict):
                next_cfg["ui"] = ui_raw
            next_cfg["state"] = "idle"
            for key in RUNTIME_STATE_FIELDS:
                next_cfg.pop(key, None)
            next_cfg["state"] = "idle"
            if not _write_json_dict(config_path, next_cfg):
                raise HTTPException(status_code=500, detail="failed to update cloned node config")
        except HTTPException:
            shutil.rmtree(new_dir, ignore_errors=True)
            raise
        except Exception as e:
            shutil.rmtree(new_dir, ignore_errors=True)
            raise HTTPException(status_code=500, detail=f"failed to clone node instance: {str(e)}")

        self.graph_runtime._log_graph_event(
            safe_target_graph_id,
            "node_cloned",
            source_graph_id=safe_source_graph_id,
            source_node_id=safe_node_id,
            node_id=safe_new_node_id,
            node_type_id=type_id or None,
        )
        self.graph_runtime._refresh_scheduled_node(safe_target_graph_id, safe_new_node_id)
        return {
            "ok": True,
            "source_graph_id": safe_source_graph_id,
            "source_node_id": safe_node_id,
            "node_id": safe_new_node_id,
            "graph_id": safe_target_graph_id,
            "type_id": type_id,
            "config_path": config_path,
        }

    def clear_node_instance_memory(self, node_id: str, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        if not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")
        try:
            cleared_files = clear_node_memory(
                self.graph_runtime._node_memory_path(safe_node_id, safe_graph_id),
                self.graph_runtime._node_messages_path(safe_node_id, safe_graph_id),
            )
        except NodeMemoryPersistenceError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        summary = self._clear_node_runtime_summary(config_path)
        self.core.node_live_outputs.clear(safe_graph_id, safe_node_id)
        return {
            "ok": True,
            "node_id": safe_node_id,
            "graph_id": safe_graph_id,
            "cleared_files": cleared_files,
            "cleared_summary_fields": summary.changed_fields,
        }

    def _clear_node_runtime_summary(self, config_path: str):
        def mutate(next_cfg: dict) -> None:
            changed = False
            if next_cfg.get("last_message") != "":
                next_cfg["last_message"] = ""
                changed = True
            for key in ("last_runtime_event", "runtime_events", "runtime_tool_calls", "last_run_at"):
                if key in next_cfg:
                    next_cfg.pop(key, None)
                    changed = True
            if changed:
                bump_node_event_seq(next_cfg)

        return node_config_service.update(config_path, mutate, effective="immediate")

    def open_node_instance_folder(self, node_id: str, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        node_dir = self.graph_runtime._node_dir(safe_graph_id, safe_node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        if not node_dir or not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")

        try:
            cfg = node_config_service.read_strict(config_path)
        except NodeConfigReadError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        working_path = resolve_agent_configured_working_path(
            SimpleNamespace(
                _agentpark_graph_id=safe_graph_id,
                config={"working_path": str((cfg if isinstance(cfg, dict) else {}).get("working_path") or "").strip()},
            )
        )
        target_dir = working_path or node_dir
        source = "working_path" if working_path else "node_folder"

        if not os.path.isdir(target_dir):
            raise HTTPException(status_code=404, detail=f"{source} is not an existing folder: {target_dir}")

        try:
            if os.name == "nt":
                subprocess.Popen(["explorer.exe", os.path.normpath(target_dir)], close_fds=True)
            else:
                raise RuntimeError("opening folders is only supported on Windows")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to open folder: {str(exc)}")

        return {"ok": True, "node_id": safe_node_id, "graph_id": safe_graph_id, "path": target_dir, "source": source}

    def list_node_instance_configs(self, graph_id: str = "", since_version: int = 0):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        base_dir = self.graph_runtime._graph_dir(safe_graph_id)
        if not base_dir or not os.path.isdir(base_dir):
            return {"nodes": [], "node_ids": [], "version": 0, "partial": bool(since_version)}
        items = []
        node_ids = []
        max_version = 0
        try:
            min_version = int(since_version or 0)
        except Exception:
            min_version = 0
        for entry in os.listdir(base_dir):
            if entry == "agents":
                continue
            config_path = os.path.join(base_dir, entry, "config.json")
            if not os.path.exists(config_path):
                continue
            node_ids.append(entry)
            config_version = _config_file_version(config_path)
            max_version = max(max_version, config_version)
            if min_version > 0 and config_version <= min_version:
                continue
            try:
                cfg = node_config_service.read_strict(config_path)
            except NodeConfigReadError as exc:
                raise HTTPException(status_code=500, detail=str(exc))
            self._apply_runtime_projection_if_needed(cfg, os.path.join(base_dir, entry))
            type_id = str(cfg.get("type_id") or "").strip()
            if type_id == "clock_node" or (type_id and "working_path" not in cfg):
                before = json.dumps(cfg, ensure_ascii=False, sort_keys=True)
                try:
                    self.graph_runtime._try_init_node_config(type_id, cfg, safe_graph_id, entry)
                except NodeMetadataError as exc:
                    raise HTTPException(status_code=500, detail=str(exc))
                after = json.dumps(cfg, ensure_ascii=False, sort_keys=True)
                if after != before:
                    _write_json_dict(config_path, cfg)
                    config_version = _config_file_version(config_path)
                    max_version = max(max_version, config_version)
            cfg.pop("schema", None)
            cfg["node_id"] = entry
            cfg["graph_id"] = safe_graph_id
            cfg["state"] = parse_node_state(cfg.get("state"))
            pending = cfg.get("pending")
            cfg["pending_count"] = len(pending) if isinstance(pending, list) else 0
            cfg["_config_version"] = config_version
            items.append(cfg)
        return {
            "nodes": items,
            "node_ids": sorted(node_ids),
            "version": max_version,
            "partial": min_version > 0,
        }

    @staticmethod
    def _apply_runtime_projection_if_needed(cfg: dict, node_dir: str) -> None:
        if (
            cfg.get("last_runtime_event")
            and cfg.get("runtime_events")
            and cfg.get("provider_request_summaries")
            and cfg.get("provider_request_totals")
        ):
            return
        projection = load_node_runtime_projection(node_dir)
        if not projection:
            return
        for key in ("last_runtime_event", "runtime_events", "provider_request_summaries", "provider_request_totals"):
            if not cfg.get(key) and projection.get(key):
                cfg[key] = projection[key]

    def update_node_instance_config(self, node_id: str, payload: dict, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        if not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        try:
            result = node_config_service.apply_webui_payload(
                config_path,
                payload,
                init_clock=lambda type_id, cfg: self.graph_runtime._try_init_node_config(
                    type_id, cfg, safe_graph_id, safe_node_id
                ),
                sync_ports=lambda type_id, cfg: self.graph_runtime._sync_node_config_ports(
                    type_id, cfg, safe_graph_id, safe_node_id
                ),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except NodeMetadataError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        except NodeConfigReadError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        except NodeConfigWriteError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        self.graph_runtime._refresh_scheduled_node(safe_graph_id, safe_node_id)
        return {"ok": True, **result.to_payload()}
