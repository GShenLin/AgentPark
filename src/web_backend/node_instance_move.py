from __future__ import annotations

import copy
import os
from contextlib import ExitStack
from typing import Any

from src.agent_groups.node_lifecycle import node_departure
from src.cron.node_lifecycle import cron_node_departure
from src.file_transaction import atomic_write_text
from src.long_term_memory.lifecycle import require_memory_idle, rebind_memory

from . import runtime_paths
from .graph_config_file import read_graph_config, write_graph_config
from .graph_grid_layout import graph_layout_lock, repair_missing_node_grid_positions, resolve_available_node_ui
from .graph_output_routes import normalize_output_routes, prune_output_routes_for_removed_node
from .graph_runtime_registry import GraphConfigReadError
from .node_config_errors import NodeConfigReadError
from .node_config_service import node_config_service
from .node_notes import NodeNotesDataError, normalize_node_notes
from .node_state_machine import parse_node_state
from .runtime_state_memory_store import runtime_state_memory_store
from .service_host import HostBoundService
from .shared import HTTPException


class NodeInstanceMove(HostBoundService):
    def move_node_instance(self, node_id: str, payload: dict, graph_id: str = ""):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be object")
        source_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        target_graph_id_raw = payload.get("target_graph_id")
        if not isinstance(target_graph_id_raw, str) or not target_graph_id_raw.strip():
            raise HTTPException(status_code=400, detail="target_graph_id is required")
        target_graph_id = self.graph_runtime._sanitize_graph_id(target_graph_id_raw)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        if source_graph_id == target_graph_id:
            raise HTTPException(status_code=409, detail="node already belongs to target graph")
        if source_graph_id.lower() == "companion" and safe_node_id.lower() == "companion":
            raise HTTPException(status_code=403, detail="canonical Companion node cannot be moved")

        graphs_root = runtime_paths._get_graphs_dir()
        source_graph_dir = self.graph_runtime._graph_dir(source_graph_id)
        target_graph_dir = self.graph_runtime._graph_dir(target_graph_id)
        source_node_dir = self.graph_runtime._node_dir(source_graph_id, safe_node_id)
        target_node_dir = self.graph_runtime._node_dir(target_graph_id, safe_node_id)
        source_config_path = self.graph_runtime._node_config_path(safe_node_id, source_graph_id)
        target_config_path = self.graph_runtime._node_config_path(safe_node_id, target_graph_id)

        if not os.path.isfile(source_config_path) or not os.path.isdir(source_node_dir):
            raise HTTPException(status_code=404, detail="node instance not found")
        if not self._graph_exists(target_graph_id, target_graph_dir):
            raise HTTPException(status_code=404, detail="target graph not found")
        if os.path.exists(target_node_dir):
            raise HTTPException(status_code=409, detail="target graph already contains this node id")
        if not self.graph_runtime._is_safe_subdir(graphs_root, source_node_dir) or not self.graph_runtime._is_safe_subdir(
            graphs_root, target_node_dir
        ):
            raise HTTPException(status_code=400, detail="invalid node path")

        try:
            source_node_config = node_config_service.read_strict(source_config_path)
        except NodeConfigReadError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        self._require_idle(source_config_path, source_node_config)
        try:
            require_memory_idle(source_node_dir)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        source_graph_config_path = os.path.join(source_graph_dir, "config.json")
        target_graph_config_path = os.path.join(target_graph_dir, "config.json")
        source_graph_before = self._read_optional_bytes(source_graph_config_path)
        target_graph_before = self._read_optional_bytes(target_graph_config_path)
        source_node_before = self._read_optional_bytes(source_config_path)
        source_event_rules = self.core.runtime_events.export_source_event_rules(source_graph_id, safe_node_id)
        target_event_rules = self.core.runtime_events.export_source_event_rules(target_graph_id, safe_node_id)
        if target_event_rules:
            raise HTTPException(status_code=409, detail="target graph already has runtime event rules for this node id")

        moved_directory = False
        runtime_state_moved = False
        source_events_removed = False
        target_events_written = False
        schedule_unregistered = False
        reservation_acquired = False
        graph_references: dict[str, Any] = {}
        rollback_errors: list[str] = []
        try:
            with (
                cron_node_departure(source_graph_dir, safe_node_id),
                node_departure(source_graph_dir, safe_node_id, reason="moved_to_graph:" + target_graph_id),
            ):
                self._reserve_idle_node(source_config_path)
                reservation_acquired = True
                self._require_no_active_execution(source_config_path)
                self.graph_runtime._unregister_scheduled_node(source_graph_id, safe_node_id)
                schedule_unregistered = True

                os.makedirs(target_graph_dir, exist_ok=True)
                with self._lock_graph_layouts(source_graph_dir, target_graph_dir):
                    repair_missing_node_grid_positions(target_graph_dir, exclude_node_ids={safe_node_id})
                    target_ui = resolve_available_node_ui(
                        target_graph_dir,
                        source_node_config.get("ui") if isinstance(source_node_config.get("ui"), dict) else None,
                        exclude_node_ids={safe_node_id},
                    )
                    os.replace(source_node_dir, target_node_dir)
                    moved_directory = True
                    rebind_memory(target_node_dir, source_graph_id, target_graph_id, safe_node_id, safe_node_id)
                    node_config_service.patch_persistent_fields(
                        target_config_path,
                        {"graph_id": target_graph_id, "ui": target_ui},
                    )

                runtime_state_memory_store.rename(source_config_path, target_config_path)
                runtime_state_moved = True
                graph_references = self._move_graph_references(
                    source_graph_id,
                    target_graph_id,
                    safe_node_id,
                    source_graph_config_path,
                    target_graph_config_path,
                )

                moved_event_handlers = 0
                if source_event_rules:
                    # The strict registry rewrite binds the rules to the moved node at
                    # its new location and prunes the now-missing source binding.
                    self.core.runtime_events.replace_source_event_rules(
                        target_graph_id, safe_node_id, source_event_rules
                    )
                    target_events_written = True
                    moved_event_handlers = sum(len(handlers) for handlers in source_event_rules.values())
                    source_events_removed = True

                self._release_reservation(target_config_path)
                reservation_acquired = False
                self.graph_runtime._refresh_scheduled_node(target_graph_id, safe_node_id)
                self.core.node_live_outputs.clear(source_graph_id, safe_node_id)
                self.graph_runtime._log_graph_event(
                    source_graph_id,
                    "node_moved_out",
                    node_id=safe_node_id,
                    target_graph_id=target_graph_id,
                )
                self.graph_runtime._log_graph_event(
                    target_graph_id,
                    "node_moved_in",
                    node_id=safe_node_id,
                    source_graph_id=source_graph_id,
                )
                return {
                    "ok": True,
                    "node_id": safe_node_id,
                    "source_graph_id": source_graph_id,
                    "target_graph_id": target_graph_id,
                    "config_path": target_config_path,
                    "ui": target_ui,
                    "removed_output_routes": int(graph_references.get("removed_output_routes") or 0),
                    "moved_node_note": bool(graph_references.get("moved_node_note")),
                    "moved_event_handlers": moved_event_handlers,
                }
        except HTTPException:
            self._rollback_move(
                source_graph_id=source_graph_id,
                target_graph_id=target_graph_id,
                node_id=safe_node_id,
                source_node_dir=source_node_dir,
                target_node_dir=target_node_dir,
                source_config_path=source_config_path,
                target_config_path=target_config_path,
                source_node_before=source_node_before,
                source_graph_config_path=source_graph_config_path,
                target_graph_config_path=target_graph_config_path,
                source_graph_before=source_graph_before,
                target_graph_before=target_graph_before,
                source_event_rules=source_event_rules,
                target_event_rules=target_event_rules,
                source_events_removed=source_events_removed,
                target_events_written=target_events_written,
                runtime_state_moved=runtime_state_moved,
                moved_directory=moved_directory,
                schedule_unregistered=schedule_unregistered,
                reservation_acquired=reservation_acquired,
                errors=rollback_errors,
            )
            raise
        except Exception as exc:
            self._rollback_move(
                source_graph_id=source_graph_id,
                target_graph_id=target_graph_id,
                node_id=safe_node_id,
                source_node_dir=source_node_dir,
                target_node_dir=target_node_dir,
                source_config_path=source_config_path,
                target_config_path=target_config_path,
                source_node_before=source_node_before,
                source_graph_config_path=source_graph_config_path,
                target_graph_config_path=target_graph_config_path,
                source_graph_before=source_graph_before,
                target_graph_before=target_graph_before,
                source_event_rules=source_event_rules,
                target_event_rules=target_event_rules,
                source_events_removed=source_events_removed,
                target_events_written=target_events_written,
                runtime_state_moved=runtime_state_moved,
                moved_directory=moved_directory,
                schedule_unregistered=schedule_unregistered,
                reservation_acquired=reservation_acquired,
                errors=rollback_errors,
            )
            detail = f"failed to move node instance: {type(exc).__name__}: {exc}"
            if rollback_errors:
                detail += "; rollback errors: " + "; ".join(rollback_errors)
            raise HTTPException(status_code=500, detail=detail) from exc

    @staticmethod
    def _graph_exists(graph_id: str, graph_dir: str) -> bool:
        return graph_id == "default" or os.path.isfile(os.path.join(graph_dir, "config.json"))

    def _require_idle(self, config_path: str, config: dict) -> None:
        if parse_node_state(config.get("state")) != "idle" or isinstance(config.get("inflight"), dict):
            raise HTTPException(status_code=409, detail="node must be idle before it can be moved")
        if isinstance(config.get("pending"), list) and config.get("pending"):
            raise HTTPException(status_code=409, detail="node has pending work and cannot be moved")
        self._require_no_active_execution(config_path)

    def _require_no_active_execution(self, config_path: str) -> None:
        cancellations = getattr(self.core, "node_cancellations", None)
        if cancellations is not None and int(cancellations.active_count(config_path)) > 0:
            raise HTTPException(status_code=409, detail="node has active work and cannot be moved")
        target = os.path.normcase(os.path.abspath(config_path))
        for run in getattr(self.core, "node_runs", {}).values():
            if not isinstance(run, dict) or run.get("status") != "running":
                continue
            run_path = os.path.normcase(os.path.abspath(str(run.get("node_config_path") or "")))
            if run_path == target:
                raise HTTPException(status_code=409, detail="node has an active run and cannot be moved")

    @staticmethod
    def _reserve_idle_node(config_path: str) -> None:
        blocked = False

        def mutate(state: dict) -> None:
            nonlocal blocked
            if (
                bool(state.get("_delete_requested"))
                or parse_node_state(state.get("state")) != "idle"
                or isinstance(state.get("inflight"), dict)
                or bool(state.get("pending"))
            ):
                blocked = True
                return
            state["_delete_requested"] = True

        runtime_state_memory_store.update(config_path, mutate)
        if blocked:
            raise HTTPException(status_code=409, detail="node became busy before it could be moved")

    @staticmethod
    def _release_reservation(config_path: str) -> None:
        runtime_state_memory_store.update(config_path, lambda state: state.pop("_delete_requested", None))

    @staticmethod
    def _lock_graph_layouts(*graph_dirs: str):
        stack = ExitStack()
        for graph_dir in sorted({os.path.normcase(os.path.abspath(path)) for path in graph_dirs}):
            stack.enter_context(graph_layout_lock(graph_dir))
        return stack

    def _move_graph_references(
        self,
        source_graph_id: str,
        target_graph_id: str,
        node_id: str,
        source_path: str,
        target_path: str,
    ) -> dict[str, Any]:
        source = self._read_graph_or_default(source_graph_id, source_path)
        target = self._read_graph_or_default(target_graph_id, target_path)
        source_routes = normalize_output_routes(source.get("output_routes"))
        next_routes, routes_changed = prune_output_routes_for_removed_node(source_routes, node_id)
        source["output_routes"] = next_routes

        try:
            source_notes = normalize_node_notes(source.get("node_notes"))
            target_notes = normalize_node_notes(target.get("node_notes"))
        except NodeNotesDataError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        note = source_notes.pop(node_id, None)
        if note is not None:
            if node_id in target_notes:
                raise HTTPException(status_code=409, detail="target graph already has a note for this node id")
            target_notes[node_id] = note
        source["node_notes"] = source_notes
        target["node_notes"] = target_notes
        source["id"] = source_graph_id
        target["id"] = target_graph_id
        source.setdefault("name", source_graph_id)
        target.setdefault("name", target_graph_id)
        write_graph_config(source_path, source)
        write_graph_config(target_path, target)
        return {
            "removed_output_routes": self._count_routes(source_routes) - self._count_routes(next_routes) if routes_changed else 0,
            "moved_node_note": note is not None,
        }

    @staticmethod
    def _count_routes(routes: dict) -> int:
        return sum(len(item.get("targets") or []) for groups in routes.values() for item in groups)

    @staticmethod
    def _read_graph_or_default(graph_id: str, path: str) -> dict:
        if not os.path.isfile(path):
            return {"id": graph_id, "name": graph_id, "output_routes": {}, "node_notes": {}}
        try:
            return copy.deepcopy(read_graph_config(path))
        except GraphConfigReadError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def _rollback_move(self, **data) -> None:
        errors: list[str] = data["errors"]

        def attempt(label: str, operation) -> None:
            try:
                operation()
            except Exception as exc:
                errors.append(f"{label}: {type(exc).__name__}: {exc}")

        if data["moved_directory"]:
            attempt(
                "remove target schedule",
                lambda: self.graph_runtime._unregister_scheduled_node(data["target_graph_id"], data["node_id"]),
            )
        attempt("restore source graph config", lambda: self._restore_file(data["source_graph_config_path"], data["source_graph_before"]))
        attempt("restore target graph config", lambda: self._restore_file(data["target_graph_config_path"], data["target_graph_before"]))
        if data["runtime_state_moved"]:
            attempt(
                "restore runtime state",
                lambda: runtime_state_memory_store.rename(data["target_config_path"], data["source_config_path"]),
            )
        if data["moved_directory"] and os.path.isdir(data["target_node_dir"]) and not os.path.exists(data["source_node_dir"]):
            attempt("restore memory owner", lambda: rebind_memory(data["target_node_dir"], data["target_graph_id"], data["source_graph_id"], data["node_id"], data["node_id"]))
            attempt("restore node directory", lambda: os.replace(data["target_node_dir"], data["source_node_dir"]))
        if data["source_node_before"] is not None and os.path.isdir(data["source_node_dir"]):
            attempt("restore node config", lambda: self._restore_file(data["source_config_path"], data["source_node_before"]))
        if data["target_events_written"]:
            attempt(
                "restore target event rules",
                lambda: self.core.runtime_events.replace_source_event_rules(
                    data["target_graph_id"], data["node_id"], data["target_event_rules"]
                ),
            )
        if data["source_events_removed"]:
            attempt(
                "restore source event rules",
                lambda: self.core.runtime_events.replace_source_event_rules(
                    data["source_graph_id"], data["node_id"], data["source_event_rules"]
                ),
            )
        if data["reservation_acquired"]:
            attempt("release node move reservation", lambda: self._release_reservation(data["source_config_path"]))
        if data["schedule_unregistered"] and os.path.isdir(data["source_node_dir"]):
            attempt(
                "restore source schedule",
                lambda: self.graph_runtime._refresh_scheduled_node(data["source_graph_id"], data["node_id"]),
            )

    @staticmethod
    def _read_optional_bytes(path: str) -> bytes | None:
        if not os.path.isfile(path):
            return None
        with open(path, "rb") as handle:
            return handle.read()

    @staticmethod
    def _restore_file(path: str, content: bytes | None) -> None:
        if content is None:
            if os.path.exists(path):
                os.remove(path)
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomic_write_text(path, content.decode("utf-8"))
