from __future__ import annotations

import json
import os

from fastapi import Request

from .node_config_errors import NodeConfigReadError
from .node_config_service import node_config_service, node_runtime_state_version
from .node_board_view import BOARD_RUNTIME_FIELDS, build_node_board_view
from .node_metadata_reader import NodeMetadataError
from .node_diagnostics_projection import node_diagnostics_projection_store
from .node_state_machine import parse_node_state
from .request_access import is_local_request
from .service_host import HostBoundService
from .shared import HTTPException, _write_json_dict


EDITOR_RUNTIME_FIELDS = {
    "state",
    "pending_count",
    "inflight",
    "_stop_requested",
    "node_event_seq",
    "last_message",
    "last_run_at",
    "goal",
    "goal_state",
}


def _config_file_version(config_path: str) -> int:
    version = 0
    try:
        version = max(version, int(os.stat(config_path).st_mtime_ns))
    except OSError:
        pass
    return max(version, node_runtime_state_version(config_path))


class NodeInstanceConfigQuery(HostBoundService):
    def list_node_instance_configs(
        self,
        graph_id: str = "",
        since_version: int = 0,
        view: str = "full",
        request: Request = None,
    ):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        self.core.graph_api.require_graph_visible(safe_graph_id, request)
        local_request = is_local_request(request)
        safe_view = str(view or "full").strip().lower()
        if safe_view not in {"full", "board"}:
            raise HTTPException(status_code=400, detail="view must be 'full' or 'board'")
        base_dir = self.graph_runtime._graph_dir(safe_graph_id)
        if not base_dir or not os.path.isdir(base_dir):
            return {
                "nodes": [],
                "node_ids": [],
                "version": 0,
                "partial": bool(since_version),
                "view": safe_view,
            }

        try:
            min_version = int(since_version or 0)
        except Exception:
            min_version = 0

        items: list[dict] = []
        node_ids: list[str] = []
        max_version = 0
        for entry in os.listdir(base_dir):
            if entry == "agents":
                continue
            config_path = os.path.join(base_dir, entry, "config.json")
            if not os.path.exists(config_path):
                continue
            persistent_cfg = self._read_persistent_config(config_path)
            if persistent_cfg.get("private") is True and not local_request:
                continue

            node_ids.append(entry)
            config_version = _config_file_version(config_path)
            max_version = max(max_version, config_version)
            if min_version > 0 and config_version <= min_version:
                continue

            cfg = (
                node_config_service.with_runtime_fields(config_path, persistent_cfg, BOARD_RUNTIME_FIELDS)
                if safe_view == "board"
                else node_config_service.with_runtime_state(config_path, persistent_cfg)
            )
            cfg, config_version = self._materialize_config(
                cfg,
                config_path=config_path,
                graph_id=safe_graph_id,
                node_id=entry,
                config_version=config_version,
                diagnostics_fields=BOARD_RUNTIME_FIELDS,
            )
            if safe_view == "board":
                cfg = build_node_board_view(cfg)
            max_version = max(max_version, config_version)
            items.append(cfg)

        return {
            "nodes": items,
            "node_ids": sorted(node_ids),
            "version": max_version,
            "partial": min_version > 0,
            "view": safe_view,
        }

    def get_node_instance_config(
        self,
        node_id: str,
        graph_id: str = "",
        view: str = "full",
        request: Request = None,
    ):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        self.core.graph_api.require_graph_visible(safe_graph_id, request)
        safe_node_id = self.graph_runtime._resolve_existing_node_id(safe_graph_id, node_id)
        self.core.node_ops.require_node_visible(safe_node_id, safe_graph_id, request)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        if not config_path or not os.path.isfile(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")

        persistent_cfg = self._read_persistent_config(config_path)
        safe_view = str(view or "full").strip().lower()
        if safe_view not in {"full", "editor"}:
            raise HTTPException(status_code=400, detail="view must be 'full' or 'editor'")
        cfg = (
            node_config_service.with_runtime_fields(config_path, persistent_cfg, EDITOR_RUNTIME_FIELDS)
            if safe_view == "editor"
            else node_config_service.with_runtime_state(config_path, persistent_cfg)
        )
        cfg, config_version = self._materialize_config(
            cfg,
            config_path=config_path,
            graph_id=safe_graph_id,
            node_id=safe_node_id,
            config_version=_config_file_version(config_path),
            diagnostics_fields=None if safe_view == "full" else set(),
        )
        return {"node": cfg, "version": config_version, "view": safe_view}

    @staticmethod
    def _read_persistent_config(config_path: str) -> dict:
        try:
            return node_config_service.read_persistent_strict(config_path)
        except NodeConfigReadError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    def _materialize_config(
        self,
        cfg: dict,
        *,
        config_path: str,
        graph_id: str,
        node_id: str,
        config_version: int,
        diagnostics_fields: set[str] | None,
    ) -> tuple[dict, int]:
        if diagnostics_fields is None or diagnostics_fields:
            cfg = node_diagnostics_projection_store.merge_missing(
                cfg,
                node_diagnostics_projection_store.read(config_path, fields=diagnostics_fields),
            )
        type_id = str(cfg.get("type_id") or "").strip()
        if type_id == "clock_node" or (type_id and "working_path" not in cfg):
            before = json.dumps(cfg, ensure_ascii=False, sort_keys=True)
            try:
                self.graph_runtime._try_init_node_config(type_id, cfg, graph_id, node_id)
            except NodeMetadataError as exc:
                raise HTTPException(status_code=500, detail=str(exc))
            after = json.dumps(cfg, ensure_ascii=False, sort_keys=True)
            if after != before:
                _write_json_dict(config_path, cfg)
                config_version = _config_file_version(config_path)

        cfg.pop("schema", None)
        cfg["node_id"] = node_id
        cfg["graph_id"] = graph_id
        cfg["state"] = parse_node_state(cfg.get("state"))
        pending = cfg.get("pending")
        cfg["pending_count"] = len(pending) if isinstance(pending, list) else 0
        cfg["_config_version"] = config_version
        return cfg, config_version

__all__ = ["NodeInstanceConfigQuery"]
