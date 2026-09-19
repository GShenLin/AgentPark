from __future__ import annotations

import os
import shutil

from src.long_term_memory.cloning import clone_memory

from . import runtime_paths
from .graph_grid_layout import graph_layout_lock, repair_missing_node_grid_positions, resolve_available_node_ui
from .node_config_errors import NodeConfigReadError
from .node_config_service import RUNTIME_STATE_FIELDS, node_config_service
from .node_instance_artifacts import rename_node_artifacts
from .service_host import HostBoundService
from .shared import HTTPException, _write_json_dict


class NodeInstanceCloning(HostBoundService):
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

        memory_root = runtime_paths._get_graphs_dir()
        if not self.graph_runtime._is_safe_subdir(memory_root, old_dir) or not self.graph_runtime._is_safe_subdir(memory_root, new_dir):
            raise HTTPException(status_code=400, detail="invalid node path")

        try:
            source_cfg = node_config_service.read_strict(old_config_path)
        except NodeConfigReadError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        type_id = str(source_cfg.get("type_id") or "").strip()

        try:
            with graph_layout_lock(self.graph_runtime._graph_dir(safe_target_graph_id)):
                repair_missing_node_grid_positions(
                    self.graph_runtime._graph_dir(safe_target_graph_id),
                    exclude_node_ids={safe_new_node_id},
                )
                resolved_ui = resolve_available_node_ui(
                    self.graph_runtime._graph_dir(safe_target_graph_id),
                    ui_raw,
                    exclude_node_ids={safe_new_node_id},
                )
                shutil.copytree(
                    old_dir, new_dir,
                    ignore=lambda directory, names: {"long_term_memory"}
                    if os.path.normcase(os.path.abspath(directory)) == os.path.normcase(os.path.abspath(old_dir)) else set(),
                )
                clone_memory(old_dir, new_dir, safe_source_graph_id, safe_target_graph_id,
                             safe_node_id, safe_new_node_id)
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
                next_cfg["ui"] = resolved_ui
                next_cfg["state"] = "idle"
                for key in RUNTIME_STATE_FIELDS:
                    next_cfg.pop(key, None)
                next_cfg["state"] = "idle"
                if not _write_json_dict(config_path, next_cfg):
                    raise HTTPException(status_code=500, detail="failed to update cloned node config")
            event_copy = self.core.runtime_events.copy_source_event_rules(
                safe_source_graph_id,
                safe_node_id,
                safe_target_graph_id,
                safe_new_node_id,
            )
        except HTTPException:
            try:
                self.core.runtime_events.remove_source_rules(safe_target_graph_id, safe_new_node_id)
            except Exception:
                pass
            shutil.rmtree(new_dir, ignore_errors=True)
            raise
        except Exception as e:
            try:
                self.core.runtime_events.remove_source_rules(safe_target_graph_id, safe_new_node_id)
            except Exception:
                pass
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
            "ui": resolved_ui,
            "event_rules": event_copy,
        }
