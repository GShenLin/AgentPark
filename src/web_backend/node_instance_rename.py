"""Rename a node with a group transaction and reversible filesystem changes."""
import os
from pathlib import Path

from src.agent_groups.contracts import GroupConflict
from src.agent_groups.node_lifecycle import node_rename
from src.file_transaction import atomic_write_text
from src.long_term_memory.lifecycle import rebind_memory, require_memory_idle
from .node_config_errors import NodeConfigReadError
from .node_config_service import node_config_service
from .node_instance_artifacts import rename_node_references_in_graph
from .runtime_state_memory_store import runtime_state_memory_store
from .service_host import HostBoundService
from .shared import HTTPException, _write_json_dict


class NodeInstanceRename(HostBoundService):
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

        try:
            require_memory_idle(old_dir)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        config_path = self.graph_runtime._node_config_path(safe_new_node_id, safe_graph_id)
        graph_path = Path(self.graph_runtime._graph_dir(safe_graph_id)) / "config.json"
        graph_before = graph_path.read_bytes() if graph_path.is_file() else None
        node_before = Path(old_config_path).read_bytes()
        moved = rebound = runtime_moved = reserved = unregistered = False
        renamed_artifacts = []
        try:
            self._reserve_rename(old_config_path)
            reserved = True
            self._require_no_active_execution(old_config_path)
            self.graph_runtime._unregister_scheduled_node(safe_graph_id, safe_node_id)
            unregistered = True
            with node_rename(str(graph_path.parent), safe_node_id, safe_new_node_id):
                if safe_new_node_id != safe_node_id:
                    os.rename(old_dir, new_dir)
                    moved = True
                    rebind_memory(new_dir, safe_graph_id, safe_graph_id, safe_node_id, safe_new_node_id)
                    rebound = True
                    runtime_state_memory_store.rename(old_config_path, config_path)
                    runtime_moved = True
                next_cfg = node_config_service.read_strict(config_path)
                next_cfg.update(node_id=safe_new_node_id, graph_id=safe_graph_id,
                                name=new_name_raw.strip() if isinstance(new_name_raw, str) and new_name_raw.strip()
                                else safe_new_node_id)
                if not _write_json_dict(config_path, next_cfg):
                    raise RuntimeError("failed to update node config")
                if moved:
                    for filename in os.listdir(new_dir):
                        destination = None
                        if filename == safe_node_id + ".md":
                            destination = safe_new_node_id + ".md"
                        elif filename.startswith(safe_node_id + "_"):
                            destination = safe_new_node_id + filename[len(safe_node_id):]
                        if destination:
                            before, after = Path(new_dir) / filename, Path(new_dir) / destination
                            if after.exists():
                                raise RuntimeError(f"renamed artifact already exists: {destination}")
                            before.rename(after)
                            renamed_artifacts.append((before, after))
                rename_node_references_in_graph(self.graph_runtime, safe_graph_id, safe_node_id,
                                                safe_new_node_id, new_name_raw)
                runtime_state_memory_store.update(config_path, lambda state: state.pop("_delete_requested", None))
                reserved = False
        except Exception as exc:
            if not reserved and not unregistered:
                raise
            errors = []
            def restore(label, operation):
                try:
                    operation()
                except Exception as failure:
                    errors.append(f"{label}: {type(failure).__name__}: {failure}")
            for before, after in reversed(renamed_artifacts):
                restore("restore artifact", lambda before=before, after=after: after.rename(before))
            if rebound:
                restore("restore memory owner", lambda: rebind_memory(new_dir, safe_graph_id, safe_graph_id,
                                                                       safe_new_node_id, safe_node_id))
            if runtime_moved:
                restore("restore runtime", lambda: runtime_state_memory_store.rename(config_path, old_config_path))
            if moved:
                restore("restore directory", lambda: os.rename(new_dir, old_dir))
            restore("restore node config", lambda: atomic_write_text(old_config_path, node_before.decode("utf-8")))
            if graph_before is not None:
                restore("restore graph", lambda: atomic_write_text(str(graph_path), graph_before.decode("utf-8")))
            elif graph_path.exists():
                restore("restore absent graph", graph_path.unlink)
            if reserved:
                restore("release reservation", lambda: runtime_state_memory_store.update(
                    old_config_path, lambda state: state.pop("_delete_requested", None)))
            if unregistered:
                restore("restore schedule", lambda: self.graph_runtime._refresh_scheduled_node(safe_graph_id, safe_node_id))
            detail = f"failed to rename node: {exc}"
            if errors:
                detail += "; rollback errors: " + "; ".join(errors)
            code = exc.status_code if isinstance(exc, HTTPException) else 409 if isinstance(exc, GroupConflict) else 500
            raise HTTPException(status_code=code, detail=detail) from exc
        self.graph_runtime._refresh_scheduled_node(safe_graph_id, safe_new_node_id)
        self.graph_runtime._log_graph_event(safe_graph_id, "node_renamed", old_node_id=safe_node_id,
                                           new_node_id=safe_new_node_id, node_type_id=type_id or None)
        return {"ok": True, "old_node_id": safe_node_id, "node_id": safe_new_node_id,
                "graph_id": safe_graph_id, "type_id": type_id, "config_path": config_path}

    @staticmethod
    def _reserve_rename(config_path):
        def reserve(state):
            if state.get("_delete_requested") or state.get("state") == "working" or state.get("inflight"):
                raise HTTPException(status_code=409, detail="node has active work and cannot be renamed")
            state["_delete_requested"] = True
        runtime_state_memory_store.update(config_path, reserve)
