from __future__ import annotations

import json
import os
from pathlib import Path

from src.agent_groups.contracts import GroupError
from src.agent_groups.deletion_restore import restore_deleted_member
from src.file_transaction import atomic_write_text
from src.workspace_settings import save_startup_graph_settings

from .deletion_undo_store import deletion_undo_store
from .domain_base import DomainBase
from .node_memory_store import restore_node_memory_records
from .shared import HTTPException


class UndoApiDomain(DomainBase):
    def restore_deletion(self, token: str):
        try:
            metadata, entry_dir = deletion_undo_store.load(token)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        kind = str(metadata.get("kind") or "").strip()
        try:
            if kind == "delete_node":
                result = self._restore_node(metadata, entry_dir)
            elif kind == "delete_graph":
                result = self._restore_graph(metadata, entry_dir)
            elif kind == "delete_dialogue":
                result = self._restore_dialogue(metadata, entry_dir)
            else:
                raise HTTPException(status_code=400, detail=f"unsupported undo entry kind: {kind}")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to restore deletion: {exc}") from exc

        try:
            deletion_undo_store.consume(token)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"restored deletion but failed to consume undo entry: {exc}") from exc
        return {"ok": True, "token": token, "kind": kind, **result}

    def _restore_node(self, metadata: dict, entry_dir: str) -> dict:
        graph_id = self.graph_runtime._sanitize_graph_id(metadata.get("graph_id"))
        node_id = self.graph_runtime._sanitize_node_id(metadata.get("node_id"))
        source = os.path.join(entry_dir, "node")
        target = self.graph_runtime._node_dir(graph_id, node_id)
        if not os.path.isdir(source):
            raise HTTPException(status_code=409, detail="undo node snapshot is missing")
        if os.path.exists(target):
            raise HTTPException(status_code=409, detail=f"cannot undo node deletion because target exists: {node_id}")
        group_snapshot_path = os.path.join(entry_dir, "group-membership.json")
        group_snapshot = None
        if os.path.isfile(group_snapshot_path):
            with open(group_snapshot_path, encoding="utf-8") as handle:
                group_snapshot = json.load(handle)
        graph_path = os.path.join(self.graph_runtime._graph_dir(graph_id), "config.json")
        graph_before = Path(graph_path).read_bytes() if os.path.isfile(graph_path) else None
        rules_before = self.core.runtime_events.export_source_event_rules(graph_id, node_id)
        moved = rules_restored = False
        try:
            with restore_deleted_member(self.graph_runtime._graph_dir(graph_id), group_snapshot):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(source, target)
                moved = True
                graph_config_snapshot = os.path.join(entry_dir, "graph-config.json")
                if os.path.isfile(graph_config_snapshot):
                    atomic_write_text(graph_path, Path(graph_config_snapshot).read_text(encoding="utf-8"))
                rules_restored = True
                self._restore_runtime_event_rules(entry_dir)
                self.graph_runtime._refresh_scheduled_node(graph_id, node_id)
        except Exception as exc:
            errors = []
            def attempt(label, operation):
                try:
                    operation()
                except Exception as failure:
                    errors.append(f"{label}: {type(failure).__name__}: {failure}")
            if moved:
                attempt("remove restored schedule", lambda: self.graph_runtime._unregister_scheduled_node(graph_id, node_id))
                if rules_restored:
                    attempt("restore event rules", lambda: self.core.runtime_events.replace_source_event_rules(
                        graph_id, node_id, rules_before))
                if graph_before is not None:
                    attempt("restore graph", lambda: atomic_write_text(graph_path, graph_before.decode("utf-8")))
                elif os.path.exists(graph_path):
                    attempt("restore absent graph", lambda: os.unlink(graph_path))
                if os.path.exists(target) and not os.path.exists(source):
                    attempt("restore undo snapshot", lambda: os.replace(target, source))
            if errors:
                raise HTTPException(status_code=500, detail=f"failed to restore node: {exc}; rollback errors: "
                                    + "; ".join(errors)) from exc
            if isinstance(exc, GroupError):
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise
        self.graph_runtime._log_graph_event(graph_id, "node_delete_undone", node_id=node_id)
        return {"graph_id": graph_id, "node_id": node_id}

    def _restore_graph(self, metadata: dict, entry_dir: str) -> dict:
        graph_id = self.graph_runtime._sanitize_graph_id(metadata.get("graph_id"))
        source = os.path.join(entry_dir, "graph")
        target = self.graph_runtime._graph_dir(graph_id)
        if not os.path.isdir(source):
            raise HTTPException(status_code=409, detail="undo graph snapshot is missing")
        if os.path.exists(target):
            raise HTTPException(status_code=409, detail=f"cannot undo graph deletion because target exists: {graph_id}")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.replace(source, target)
        try:
            for node_id in os.listdir(target):
                if os.path.isfile(os.path.join(target, node_id, "config.json")):
                    self.graph_runtime._refresh_scheduled_node(graph_id, node_id, persist=False)
            self.graph_runtime._persist_scheduled_registry()
            if bool(metadata.get("startup_was_selected")):
                save_startup_graph_settings(graph_id, str(metadata.get("startup_graph_name") or graph_id))
            self._restore_runtime_event_rules(entry_dir)
            self.graph_runtime._log_graph_event(graph_id, "graph_delete_undone")
        except Exception:
            self.graph_runtime._unregister_scheduled_graph(graph_id)
            if os.path.exists(target) and not os.path.exists(source):
                os.replace(target, source)
            raise
        return {"graph_id": graph_id}

    def _restore_runtime_event_rules(self, entry_dir: str) -> None:
        snapshot_path = os.path.join(entry_dir, "runtime-event-rules.json")
        if not os.path.isfile(snapshot_path):
            return
        with open(snapshot_path, "r", encoding="utf-8") as handle:
            removed_rules = json.load(handle)
        self.core.runtime_events.restore_source_rules(removed_rules)

    def _restore_dialogue(self, metadata: dict, entry_dir: str) -> dict:
        graph_id = self.graph_runtime._sanitize_graph_id(metadata.get("graph_id"))
        node_id = self.graph_runtime._sanitize_node_id(metadata.get("node_id"))
        node_dir = self.graph_runtime._node_dir(graph_id, node_id)
        config_path = self.graph_runtime._node_config_path(node_id, graph_id)
        if not os.path.isfile(config_path):
            raise HTTPException(status_code=409, detail="cannot undo dialogue deletion because the node no longer exists")
        records_path = os.path.join(entry_dir, "records.json")
        with open(records_path, "r", encoding="utf-8") as handle:
            snapshots = json.load(handle)
        if not isinstance(snapshots, list):
            raise HTTPException(status_code=409, detail="undo dialogue snapshot is invalid")
        resolved_snapshots = []
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue
            messages_path = os.path.abspath(os.path.join(node_dir, str(snapshot.get("messages_path") or "")))
            memory_path = os.path.abspath(os.path.join(node_dir, str(snapshot.get("memory_path") or "")))
            if not self.graph_runtime._is_safe_subdir(node_dir, messages_path):
                raise HTTPException(status_code=409, detail="undo dialogue snapshot points outside the node")
            if not self.graph_runtime._is_safe_subdir(node_dir, memory_path):
                raise HTTPException(status_code=409, detail="undo dialogue snapshot points outside the node")
            resolved_snapshots.append(
                {
                    "messages_path": messages_path,
                    "memory_path": memory_path,
                    "records": list(snapshot.get("records") or []),
                }
            )
        restored = restore_node_memory_records(
            self.graph_runtime._node_memory_path(node_id, graph_id),
            self.graph_runtime._node_messages_path(node_id, graph_id),
            resolved_snapshots,
        )
        return {"graph_id": graph_id, "node_id": node_id, "restored": restored}


__all__ = ["UndoApiDomain"]
