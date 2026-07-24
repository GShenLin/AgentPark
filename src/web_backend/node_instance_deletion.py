import os

from . import runtime_paths
from .deletion_undo_store import deletion_undo_store
from .node_deletion import NodeDeletionBlocked
from .node_deletion import delete_node_directory
from .node_instance_artifacts import prune_node_references_in_graph
from .runtime_state_memory_store import runtime_state_memory_store
from .service_host import HostBoundService
from .shared import HTTPException


class NodeInstanceDeletion(HostBoundService):
    def delete_node_instance(self, node_id: str, graph_id: str = "", wait_timeout_seconds: float = 10.0):
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        node_dir = self.graph_runtime._node_dir(safe_graph_id, safe_node_id)
        memory_root = runtime_paths._get_graphs_dir()
        undo_entry = deletion_undo_store.begin(
            "delete_node",
            {"graph_id": safe_graph_id, "node_id": safe_node_id},
        )
        archived = False
        removed_event_rules: dict = {}
        try:
            event_cleanup = self.core.runtime_events.remove_source_rules(safe_graph_id, safe_node_id)
            removed_event_rules = dict(event_cleanup.get("removed_rules") or {})
            if undo_entry is not None and removed_event_rules:
                deletion_undo_store.write_json(undo_entry, "runtime-event-rules.json", removed_event_rules)
        except Exception as exc:
            deletion_undo_store.discard(undo_entry)
            raise HTTPException(status_code=500, detail=f"failed to remove node event config: {str(exc)}") from exc
        self.graph_runtime._unregister_scheduled_node(safe_graph_id, safe_node_id)
        try:
            result = delete_node_directory(
                core=self.core,
                graph_runtime=self.graph_runtime,
                graph_id=safe_graph_id,
                node_id=safe_node_id,
                node_dir=node_dir,
                memory_root=memory_root,
                wait_timeout_seconds=wait_timeout_seconds,
                archive_directory=(
                    (lambda source: deletion_undo_store.archive_directory(undo_entry, source, "node"))
                    if undo_entry is not None
                    else None
                ),
            )
            archived = undo_entry is not None
        except FileNotFoundError:
            deletion_undo_store.discard(undo_entry)
            raise HTTPException(status_code=404, detail="node instance not found")
        except NodeDeletionBlocked as exc:
            if removed_event_rules:
                self.core.runtime_events.restore_source_rules(removed_event_rules)
            deletion_undo_store.discard(undo_entry)
            raise HTTPException(status_code=409, detail=f"node deletion is blocked: {str(exc)}")
        except Exception as exc:
            if archived and undo_entry is not None:
                archived_node = os.path.join(str(undo_entry["temp_dir"]), "node")
                if os.path.exists(archived_node) and not os.path.exists(node_dir):
                    os.makedirs(os.path.dirname(node_dir), exist_ok=True)
                    os.replace(archived_node, node_dir)
            deletion_undo_store.discard(undo_entry)
            if os.path.exists(node_dir):
                self.graph_runtime._refresh_scheduled_node(safe_graph_id, safe_node_id)
            if removed_event_rules:
                self.core.runtime_events.restore_source_rules(removed_event_rules)
            raise HTTPException(status_code=500, detail=f"failed to delete node instance: {str(exc)}")
        graph_config_path = os.path.join(self.graph_runtime._graph_dir(safe_graph_id), "config.json")
        graph_config_before = b""
        if os.path.isfile(graph_config_path):
            with open(graph_config_path, "rb") as handle:
                graph_config_before = handle.read()
        try:
            prune_node_references_in_graph(self.graph_runtime, safe_graph_id, safe_node_id)
            if undo_entry is not None and graph_config_before:
                deletion_undo_store.write_bytes(undo_entry, "graph-config.json", graph_config_before)
            undo_token = deletion_undo_store.commit(undo_entry) if undo_entry is not None else ""
        except Exception:
            if undo_entry is not None:
                archived_node = os.path.join(str(undo_entry["temp_dir"]), "node")
                if os.path.exists(archived_node) and not os.path.exists(node_dir):
                    os.makedirs(os.path.dirname(node_dir), exist_ok=True)
                    os.replace(archived_node, node_dir)
                deletion_undo_store.discard(undo_entry)
            if graph_config_before:
                from src.file_transaction import atomic_write_text

                atomic_write_text(graph_config_path, graph_config_before.decode("utf-8"))
            self.graph_runtime._refresh_scheduled_node(safe_graph_id, safe_node_id)
            if removed_event_rules:
                self.core.runtime_events.restore_source_rules(removed_event_rules)
            raise
        runtime_state_memory_store.clear(self.graph_runtime._node_config_path(safe_node_id, safe_graph_id))
        self.graph_runtime._log_graph_event(
            safe_graph_id,
            "node_deleted",
            node_id=safe_node_id,
            active_cancelled=result.active_cancelled,
            stopped_runs=result.stopped_runs,
            cleared_pending=result.cleared_pending,
            cleared_inflight=result.cleared_inflight,
        )
        return {
            "ok": True,
            "node_id": safe_node_id,
            "graph_id": safe_graph_id,
            "undo_token": undo_token or None,
            "removed_event_handlers": int(event_cleanup.get("removed_handlers") or 0),
            **result.to_payload(),
        }
