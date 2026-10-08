import os

from src.agent_groups.node_lifecycle import node_departure
from src.cron.node_lifecycle import cron_node_departure

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
        if not node_dir or not os.path.isdir(node_dir):
            raise HTTPException(status_code=404, detail="node instance not found")

        try:
            undo_entry = deletion_undo_store.begin(
                "delete_node",
                {"graph_id": safe_graph_id, "node_id": safe_node_id},
                for_rollback=True,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"failed to initialize node deletion: {type(exc).__name__}: {str(exc)}",
            ) from exc

        archived = False
        schedule_unregistered = False
        removed_event_rules: dict = {}
        try:
            event_cleanup = self.core.runtime_events.remove_source_rules(safe_graph_id, safe_node_id)
            removed_event_rules = dict(event_cleanup.get("removed_rules") or {})
            if undo_entry is not None and removed_event_rules:
                deletion_undo_store.write_json(undo_entry, "runtime-event-rules.json", removed_event_rules)
            schedule_unregistered = True
            self.graph_runtime._unregister_scheduled_node(safe_graph_id, safe_node_id)
        except Exception as exc:
            rollback_errors = self._rollback_delete_preparation(
                safe_graph_id,
                safe_node_id,
                node_dir,
                undo_entry,
                removed_event_rules,
                schedule_unregistered=schedule_unregistered,
            )
            raise HTTPException(
                status_code=500,
                detail=self._failure_detail("failed to prepare node deletion", exc, rollback_errors),
            ) from exc

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
            rollback_errors = self._rollback_delete_preparation(
                safe_graph_id,
                safe_node_id,
                node_dir,
                undo_entry,
                removed_event_rules,
                schedule_unregistered=schedule_unregistered,
            )
            detail = "node instance not found"
            if rollback_errors:
                detail += "; rollback errors: " + "; ".join(rollback_errors)
            raise HTTPException(status_code=404, detail=detail)
        except NodeDeletionBlocked as exc:
            rollback_errors = self._rollback_delete_preparation(
                safe_graph_id,
                safe_node_id,
                node_dir,
                undo_entry,
                removed_event_rules,
                schedule_unregistered=schedule_unregistered,
            )
            detail = f"node deletion is blocked: {str(exc)}"
            if rollback_errors:
                detail += "; rollback errors: " + "; ".join(rollback_errors)
            raise HTTPException(status_code=409, detail=detail)
        except Exception as exc:
            if archived and undo_entry is not None:
                archived_node = os.path.join(str(undo_entry["temp_dir"]), "node")
                if os.path.exists(archived_node) and not os.path.exists(node_dir):
                    os.makedirs(os.path.dirname(node_dir), exist_ok=True)
                    os.replace(archived_node, node_dir)
            rollback_errors = self._rollback_delete_preparation(
                safe_graph_id,
                safe_node_id,
                node_dir,
                undo_entry,
                removed_event_rules,
                schedule_unregistered=schedule_unregistered,
            )
            raise HTTPException(
                status_code=500,
                detail=self._failure_detail("failed to delete node instance", exc, rollback_errors),
            ) from exc
        graph_config_path = os.path.join(self.graph_runtime._graph_dir(safe_graph_id), "config.json")
        graph_config_before = b""
        try:
            if os.path.isfile(graph_config_path):
                with open(graph_config_path, "rb") as handle:
                    graph_config_before = handle.read()
            with (
                cron_node_departure(self.graph_runtime._graph_dir(safe_graph_id), safe_node_id),
                node_departure(self.graph_runtime._graph_dir(safe_graph_id), safe_node_id,
                               reason="deleted") as group_snapshot,
            ):
                if group_snapshot is not None:
                    deletion_undo_store.write_json(undo_entry, "group-membership.json", group_snapshot)
                prune_node_references_in_graph(self.graph_runtime, safe_graph_id, safe_node_id)
                if undo_entry is not None and graph_config_before:
                    deletion_undo_store.write_bytes(undo_entry, "graph-config.json", graph_config_before)
                undo_token = deletion_undo_store.commit(undo_entry) if undo_entry is not None else ""
        except Exception as exc:
            rollback_errors = []
            if graph_config_before:
                from src.file_transaction import atomic_write_text
                try:
                    atomic_write_text(graph_config_path, graph_config_before.decode("utf-8"))
                except Exception as failure:
                    rollback_errors.append(f"restore graph: {type(failure).__name__}: {failure}")
            rollback_errors.extend(self._rollback_delete_preparation(
                safe_graph_id, safe_node_id, node_dir, undo_entry, removed_event_rules,
                schedule_unregistered=schedule_unregistered))
            raise HTTPException(status_code=500, detail=self._failure_detail(
                "failed to commit node deletion", exc, rollback_errors)) from exc
        if undo_entry is not None and not undo_entry.get("retained", True):
            try:
                deletion_undo_store.discard(undo_entry)
            except OSError as exc:
                raise HTTPException(status_code=500, detail=f"node deleted but temporary archive cleanup failed: {exc}") from exc
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

    def _rollback_delete_preparation(
        self,
        graph_id: str,
        node_id: str,
        node_dir: str,
        undo_entry: dict | None,
        removed_event_rules: dict,
        *,
        schedule_unregistered: bool,
    ) -> list[str]:
        errors: list[str] = []
        try:
            if undo_entry is not None:
                archived_node = os.path.join(str(undo_entry["temp_dir"]), "node")
                if os.path.exists(archived_node):
                    if os.path.exists(node_dir):
                        raise RuntimeError("both archived and live node directories exist; rollback snapshot retained")
                    os.replace(archived_node, node_dir)
            deletion_undo_store.discard(undo_entry)
        except Exception as exc:
            errors.append(f"discard undo entry: {type(exc).__name__}: {str(exc)}")
        if removed_event_rules:
            try:
                self.core.runtime_events.restore_source_rules(removed_event_rules)
            except Exception as exc:
                errors.append(f"restore event rules: {type(exc).__name__}: {str(exc)}")
        if schedule_unregistered and os.path.exists(node_dir):
            try:
                runtime_state_memory_store.update(
                    self.graph_runtime._node_config_path(node_id, graph_id),
                    lambda state: state.pop("_delete_requested", None))
                self.graph_runtime._refresh_scheduled_node(graph_id, node_id)
            except Exception as exc:
                errors.append(f"restore schedule: {type(exc).__name__}: {str(exc)}")
        return errors

    @staticmethod
    def _failure_detail(prefix: str, error: Exception, rollback_errors: list[str]) -> str:
        detail = f"{prefix}: {type(error).__name__}: {str(error)}"
        if rollback_errors:
            detail += "; rollback errors: " + "; ".join(rollback_errors)
        return detail
