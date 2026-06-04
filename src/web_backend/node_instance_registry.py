import json
import math
import os
import shutil

from . import runtime_paths
from .node_config_errors import NodeConfigWriteError
from .node_metadata_reader import NodeMetadataError
from .node_memory_store import NodeMemoryPersistenceError
from .service_host import HostBoundService
from .shared import (
    HTTPException,
    _parse_node_state,
    _read_json_dict,
    _write_json_dict,
)


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

        cfg = _read_json_dict(old_config_path)
        if not isinstance(cfg, dict) or not cfg:
            cfg = {"node_id": safe_node_id, "graph_id": safe_graph_id}
        type_id = str(cfg.get("type_id") or "").strip()

        try:
            if safe_new_node_id != safe_node_id:
                os.rename(old_dir, new_dir)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to rename node directory: {str(e)}")

        config_path = self.graph_runtime._node_config_path(safe_new_node_id, safe_graph_id)
        next_cfg = _read_json_dict(config_path)
        if not isinstance(next_cfg, dict) or not next_cfg:
            next_cfg = cfg
        next_cfg["node_id"] = safe_new_node_id
        next_cfg["graph_id"] = safe_graph_id
        next_cfg["name"] = safe_new_node_id
        if not _write_json_dict(config_path, next_cfg):
            raise HTTPException(status_code=500, detail="failed to update node config")

        if safe_new_node_id != safe_node_id and os.path.isdir(new_dir):
            self._rename_node_artifacts(new_dir, safe_node_id, safe_new_node_id)

        self._rename_node_references_in_graph(safe_graph_id, safe_node_id, safe_new_node_id, new_name_raw)

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

    def _rename_node_artifacts(self, new_dir: str, old_node_id: str, new_node_id: str) -> None:
        old_memory = os.path.join(new_dir, f"{old_node_id}.md")
        new_memory = os.path.join(new_dir, f"{new_node_id}.md")
        try:
            if os.path.exists(old_memory) and not os.path.exists(new_memory):
                os.rename(old_memory, new_memory)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to rename node memory artifact: {str(exc)}")
        old_prefix = f"{old_node_id}_"
        new_prefix = f"{new_node_id}_"
        try:
            filenames = os.listdir(new_dir)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to list node artifacts: {str(exc)}")
        for filename in filenames:
            if filename.startswith(old_prefix):
                src_path = os.path.join(new_dir, filename)
                dst_path = os.path.join(new_dir, f"{new_prefix}{filename[len(old_prefix):]}")
                try:
                    if not os.path.exists(dst_path):
                        os.rename(src_path, dst_path)
                except Exception as exc:
                    raise HTTPException(status_code=500, detail=f"failed to rename node artifact: {str(exc)}")

    def _rename_node_references_in_graph(self, graph_id: str, old_node_id: str, new_node_id: str, new_name_raw) -> None:
        graph_cfg = self.graph_runtime._read_graph_config(graph_id)
        graph_changed = False
        if isinstance(graph_cfg, dict) and graph_cfg:
            nodes = graph_cfg.get("nodes")
            if isinstance(nodes, list):
                for node_item in nodes:
                    if isinstance(node_item, dict) and str(node_item.get("id") or "").strip() == old_node_id:
                        node_item["id"] = new_node_id
                        if isinstance(new_name_raw, str) and new_name_raw.strip():
                            node_item["name"] = new_name_raw.strip()
                        graph_changed = True
            links = graph_cfg.get("links")
            if isinstance(links, list):
                for link in links:
                    if not isinstance(link, dict):
                        continue
                    for side in ("from", "to"):
                        endpoint = link.get(side)
                        if isinstance(endpoint, dict):
                            if str(endpoint.get("node") or "").strip() == old_node_id:
                                endpoint["node"] = new_node_id
                                graph_changed = True
                        elif isinstance(endpoint, str) and endpoint.strip() == old_node_id:
                            link[side] = new_node_id
                            graph_changed = True
        if graph_changed:
            graph_dir = os.path.join(runtime_paths._get_graphs_dir(), graph_id)
            os.makedirs(graph_dir, exist_ok=True)
            graph_cfg["id"] = graph_id
            try:
                with open(os.path.join(graph_dir, "config.json"), "w", encoding="utf-8") as f:
                    json.dump(graph_cfg, f, ensure_ascii=False, indent=2)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"failed to update graph config: {str(e)}")

    def delete_node_instance(self, node_id: str, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        node_dir = self.graph_runtime._node_dir(safe_graph_id, safe_node_id)
        memory_root = os.path.join(runtime_paths._get_runtime_root(), "memories")
        removed_dir = False
        if node_dir:
            try:
                if not self.graph_runtime._is_safe_subdir(memory_root, node_dir):
                    raise RuntimeError("refusing to delete outside memory root")
                dir_real = os.path.realpath(node_dir)
                if os.path.isdir(dir_real):
                    shutil.rmtree(dir_real)
                    removed_dir = True
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"failed to delete node instance: {str(exc)}")
        if not removed_dir:
            raise HTTPException(status_code=404, detail="node instance not found")
        return {"ok": True, "node_id": safe_node_id, "graph_id": safe_graph_id, "removed_memory_dir": removed_dir}

    def list_node_instance_configs(self, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        base_dir = self.graph_runtime._graph_dir(safe_graph_id)
        if not base_dir or not os.path.isdir(base_dir):
            return {"nodes": []}
        items = []
        for entry in os.listdir(base_dir):
            if entry == "agents":
                continue
            config_path = os.path.join(base_dir, entry, "config.json")
            if not os.path.exists(config_path):
                continue
            cfg = _read_json_dict(config_path)
            if isinstance(cfg, dict) and cfg:
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
                cfg.pop("schema", None)
                cfg["state"] = _parse_node_state(cfg.get("state"))
                pending = cfg.get("pending")
                cfg["pending_count"] = len(pending) if isinstance(pending, list) else 0
                items.append(cfg)
        return {"nodes": items}

    def update_node_instance_config(self, node_id: str, payload: dict, graph_id: str = ""):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        if not config_path or not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")

        next_cfg = _read_json_dict(config_path)
        if not isinstance(next_cfg, dict) or not next_cfg:
            next_cfg = {"node_id": safe_node_id, "graph_id": safe_graph_id}

        reserved = {
            "node_id", "type_id", "name", "graph_id", "state", "ui", "pending",
            "pending_count", "inflight", "schema", "last_message", "last_runtime_event", "runtime_events", "runtime_tool_calls", "last_run_at",
            "input_num", "output_num",
        }
        fields = payload.get("fields")
        if fields is not None and not isinstance(fields, dict):
            raise HTTPException(status_code=400, detail="fields must be object")
        if isinstance(fields, dict):
            for k, v in fields.items():
                if isinstance(k, str) and k.strip() and k not in reserved:
                    next_cfg[k] = v

        next_cfg.pop("schema", None)

        if "ui" in payload:
            ui = payload.get("ui")
            if ui is not None and not isinstance(ui, dict):
                raise HTTPException(status_code=400, detail="ui must be object")
            if isinstance(ui, dict):
                x = float(ui.get("x") or 0)
                y = float(ui.get("y") or 0)
                if not math.isfinite(x):
                    x = 0
                if not math.isfinite(y):
                    y = 0
                next_cfg["ui"] = {"x": max(0, int(round(x))), "y": max(0, int(round(y)))}

        type_id = str(next_cfg.get("type_id") or "").strip()
        if type_id:
            if type_id == "clock_node":
                try:
                    self.graph_runtime._try_init_node_config(type_id, next_cfg, safe_graph_id, safe_node_id)
                except NodeMetadataError as exc:
                    raise HTTPException(status_code=500, detail=str(exc))
            try:
                self.graph_runtime._sync_node_config_ports(type_id, next_cfg, safe_graph_id, safe_node_id)
            except NodeMetadataError as exc:
                raise HTTPException(status_code=500, detail=str(exc))

        if not _write_json_dict(config_path, next_cfg):
            raise HTTPException(status_code=500, detail="failed to write node config")
        return {"ok": True}
