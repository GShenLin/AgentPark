from __future__ import annotations

import copy
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from src.file_transaction import atomic_write_text, run_with_interprocess_lock
from src.workspace_settings import get_workspace_cache_dir

from . import runtime_paths
from .node_config_service import node_config_service
from .node_event_sequence import bump_node_event_seq
from .node_state_machine import parse_node_state
from .restart_recovery_contract import (
    RESTART_RECOVERY_SCHEMA_VERSION,
    RESTART_TAG_KIND,
    RESTORED_RUNTIME_FIELDS,
    RestartRecoveryError,
    build_restart_checkpoint,
    build_restart_model_state,
    validate_restart_checkpoint,
)
from .runtime_state_memory_store import runtime_state_memory_store


RESTART_CACHE_DIRNAME = "restart"
RESTART_STATE_DIRNAME = "state"
RESTART_LOCK_FILENAME = ".restart-recovery.lock"


class RestartRecoveryCoordinator:
    def __init__(self, core: object, *, cache_dir: str | None = None, graphs_dir: str | None = None) -> None:
        self.core = core
        self._cache_dir_override = str(cache_dir or "").strip()
        self._graphs_dir_override = str(graphs_dir or "").strip()

    def capture_running_nodes(self) -> dict[str, Any]:
        return run_with_interprocess_lock(self._lock_path(), self._capture_running_nodes_locked)

    def recover_pending_nodes(self) -> dict[str, Any]:
        return run_with_interprocess_lock(self._lock_path(), self._recover_pending_nodes_locked)

    def complete_node_recovery(self, reference: object) -> dict[str, Any]:
        if not isinstance(reference, dict):
            return {"matched": False, "removed": False}
        restart_id = str(reference.get("restart_id") or "").strip()
        graph_id = str(reference.get("graph_id") or "").strip()
        node_id = str(reference.get("node_id") or "").strip()
        if not restart_id or not graph_id or not node_id:
            return {"matched": False, "removed": False}

        def complete() -> dict[str, Any]:
            tag_path = self._tag_path(graph_id, node_id)
            tag = self._read_json_object(tag_path, required=False)
            if not tag or str(tag.get("restart_id") or "").strip() != restart_id:
                return {"matched": False, "removed": False}
            state_path = self._resolve_state_path(tag)
            completed_tag = dict(tag)
            completed_tag["status"] = "completed"
            completed_tag["completed_at"] = self._now()
            self._write_json(tag_path, completed_tag)
            self._remove_file(state_path)
            self._remove_file(tag_path)
            return {"matched": True, "removed": True, "restart_id": restart_id}

        return run_with_interprocess_lock(self._lock_path(), complete)

    def _capture_running_nodes_locked(self) -> dict[str, Any]:
        restart_id = uuid.uuid4().hex
        prepared: list[dict[str, Any]] = []
        unsafe: list[str] = []
        for graph_id, node_id, type_id, config_path in self._iter_node_configs():
            snapshot = runtime_state_memory_store.snapshot(config_path, include_defaults=False)
            if parse_node_state(snapshot.get("state")) != "working":
                continue
            inflight = snapshot.get("inflight")
            if not isinstance(inflight, dict):
                if type_id != "clock_node":
                    unsafe.append(f"{graph_id}/{node_id}")
                continue
            checkpoint = build_restart_checkpoint(
                restart_id=restart_id,
                graph_id=graph_id,
                node_id=node_id,
                type_id=type_id,
                config_path=config_path,
                graphs_dir=self._graphs_dir(),
                runtime_state=snapshot,
            )
            state_path = self._state_path(restart_id, graph_id, node_id)
            tag_path = self._tag_path(graph_id, node_id)
            previous_tag = self._read_json_object(tag_path, required=False)
            if previous_tag:
                self._require_tag_identity(previous_tag, graph_id, node_id, tag_path)
            tag = {
                "schema_version": RESTART_RECOVERY_SCHEMA_VERSION,
                "kind": RESTART_TAG_KIND,
                "restart_id": restart_id,
                "graph_id": graph_id,
                "node_id": node_id,
                "node_type_id": type_id,
                "status": "pending",
                "created_at": checkpoint["created_at"],
                "created_by_runtime_owner_id": str(getattr(self.core, "runtime_owner_id", "") or ""),
                "state_path": os.path.relpath(state_path, self._restart_dir()).replace("\\", "/"),
                "config_relative_path": checkpoint["config_relative_path"],
            }
            self._validate_json_payload(checkpoint)
            self._validate_json_payload(tag)
            prepared.append(
                {
                    "graph_id": graph_id,
                    "node_id": node_id,
                    "config_path": config_path,
                    "state_path": state_path,
                    "tag_path": tag_path,
                    "checkpoint": checkpoint,
                    "tag": tag,
                    "previous_tag": previous_tag,
                }
            )

        if unsafe:
            raise RestartRecoveryError(
                "working nodes have no recoverable inflight state: " + ", ".join(sorted(unsafe))
            )

        written: list[dict[str, Any]] = []
        try:
            for item in prepared:
                written.append(item)
                self._write_json(item["state_path"], item["checkpoint"])
                self._write_json(item["tag_path"], item["tag"])
        except Exception:
            for item in reversed(written):
                previous_tag = item["previous_tag"]
                if previous_tag:
                    self._write_json(item["tag_path"], previous_tag)
                else:
                    self._remove_file(item["tag_path"])
                self._remove_file(item["state_path"])
            raise

        for item in prepared:
            previous_tag = item["previous_tag"]
            if previous_tag:
                previous_state = self._resolve_state_path(previous_tag)
                if os.path.normcase(previous_state) != os.path.normcase(item["state_path"]):
                    self._remove_file(previous_state)
        nodes = [
            {key: item[key] for key in ("graph_id", "node_id", "state_path", "tag_path")}
            for item in prepared
        ]
        return {"ok": True, "restart_id": restart_id, "captured": len(nodes), "nodes": nodes}

    def _recover_pending_nodes_locked(self) -> dict[str, Any]:
        restart_dir = self._restart_dir()
        if not os.path.isdir(restart_dir):
            return {"ok": True, "recovered": 0, "claimed": 0, "completed_cleaned": 0, "failures": []}
        owner_id = str(getattr(self.core, "runtime_owner_id", "") or "").strip()
        recovered = 0
        already_claimed = 0
        completed_cleaned = 0
        failures: list[dict[str, str]] = []
        for tag_path in sorted(Path(restart_dir).glob("*.json"), key=lambda item: item.name.lower()):
            try:
                tag = self._read_json_object(str(tag_path), required=True)
                self._validate_tag(tag, str(tag_path))
                if tag.get("status") == "completed":
                    self._remove_file(self._resolve_state_path(tag))
                    self._remove_file(str(tag_path))
                    completed_cleaned += 1
                    continue
                if tag.get("status") == "claimed" and tag.get("claimed_by_runtime_owner_id") == owner_id:
                    already_claimed += 1
                    continue
                checkpoint = self._read_json_object(self._resolve_state_path(tag), required=True)
                validate_restart_checkpoint(checkpoint, tag)
                self._claim_and_enqueue(str(tag_path), tag, checkpoint, owner_id)
                recovered += 1
            except Exception as exc:
                failures.append({"tag_path": str(tag_path), "error": f"{type(exc).__name__}: {exc}"})
        return {
            "ok": not failures,
            "recovered": recovered,
            "claimed": already_claimed,
            "completed_cleaned": completed_cleaned,
            "failures": failures,
        }

    def _claim_and_enqueue(self, tag_path: str, tag: dict[str, Any], checkpoint: dict[str, Any], owner_id: str) -> None:
        graph_id = str(tag["graph_id"])
        node_id = str(tag["node_id"])
        config_path = self._config_path_from_relative(str(tag["config_relative_path"]))
        persistent = node_config_service.read_persistent_strict(config_path)
        actual_node_id = str(persistent.get("node_id") or Path(config_path).parent.name).strip()
        if actual_node_id != node_id:
            raise RestartRecoveryError(f"restart checkpoint node identity changed: {node_id} != {actual_node_id}")
        current = runtime_state_memory_store.snapshot(config_path)
        if parse_node_state(current.get("state")) != "idle" or isinstance(current.get("inflight"), dict):
            raise RestartRecoveryError(f"node is not idle before restart recovery: {graph_id}/{node_id}")

        claimed_tag = dict(tag)
        claimed_tag["status"] = "claimed"
        claimed_tag["claimed_at"] = self._now()
        claimed_tag["claimed_by_runtime_owner_id"] = owner_id
        self._write_json(tag_path, claimed_tag)
        try:
            snapshot = checkpoint["runtime_state"]
            inflight = copy.deepcopy(snapshot["inflight"])
            inflight["_runtime_owner_id"] = owner_id
            inflight["_restart_recovery"] = {
                "schema_version": RESTART_RECOVERY_SCHEMA_VERSION,
                "restart_id": str(tag["restart_id"]),
                "graph_id": graph_id,
                "node_id": node_id,
                "model_state": build_restart_model_state(checkpoint),
            }
            pending = [inflight]
            for item in snapshot.get("pending") or []:
                if not isinstance(item, dict):
                    raise RestartRecoveryError("restart checkpoint pending items must be objects")
                next_item = copy.deepcopy(item)
                next_item["_runtime_owner_id"] = owner_id
                pending.append(next_item)
            for item in current.get("pending") or []:
                if not isinstance(item, dict):
                    raise RestartRecoveryError("current pending items must be objects")
                pending.append(copy.deepcopy(item))

            def restore(payload: dict[str, Any]) -> None:
                for field in RESTORED_RUNTIME_FIELDS:
                    if field in snapshot:
                        payload[field] = copy.deepcopy(snapshot[field])
                payload["state"] = "idle"
                payload["pending"] = pending
                payload["pending_count"] = len(pending)
                payload.pop("inflight", None)
                payload.pop("inflight_at", None)
                payload.pop("_stop_requested", None)
                payload["node_event_seq"] = max(
                    int(payload.get("node_event_seq") or 0),
                    int(current.get("node_event_seq") or 0),
                )
                bump_node_event_seq(payload)

            runtime_state_memory_store.update(config_path, restore)
            self.core.graph_runtime._ensure_graph_runner(graph_id)
            self.core.graph_runtime._wake_graph_runner(graph_id)
            self.core.graph_runtime._log_graph_event(
                graph_id,
                "restart_recovery_enqueued",
                node_instance_id=node_id,
                trace_id=str(inflight.get("trace_id") or ""),
                restart_id=str(tag["restart_id"]),
                recovered_pending_count=len(pending),
            )
        except Exception:
            runtime_state_memory_store.replace(config_path, current)
            retry_tag = dict(tag)
            retry_tag["status"] = "pending"
            retry_tag.pop("claimed_at", None)
            retry_tag.pop("claimed_by_runtime_owner_id", None)
            self._write_json(tag_path, retry_tag)
            raise

    def _iter_node_configs(self):
        graphs_dir = self._graphs_dir()
        if not os.path.isdir(graphs_dir):
            return
        for graph_entry in sorted(os.listdir(graphs_dir)):
            graph_dir = os.path.join(graphs_dir, graph_entry)
            if not os.path.isdir(graph_dir):
                continue
            graph_id = self.core.graph_runtime._sanitize_graph_id(graph_entry)
            for node_entry in sorted(os.listdir(graph_dir)):
                if node_entry == "agents":
                    continue
                config_path = os.path.join(graph_dir, node_entry, "config.json")
                if not os.path.isfile(config_path):
                    continue
                persistent = node_config_service.read_persistent_strict(config_path)
                node_id = str(persistent.get("node_id") or node_entry).strip()
                type_id = str(persistent.get("type_id") or "").strip()
                if node_id and type_id:
                    yield graph_id, node_id, type_id, config_path

    def _validate_tag(self, tag: dict[str, Any], tag_path: str) -> None:
        if tag.get("schema_version") != RESTART_RECOVERY_SCHEMA_VERSION or tag.get("kind") != RESTART_TAG_KIND:
            raise RestartRecoveryError(f"invalid restart tag contract: {tag_path}")
        graph_id = str(tag.get("graph_id") or "").strip()
        node_id = str(tag.get("node_id") or "").strip()
        restart_id = str(tag.get("restart_id") or "").strip()
        if not graph_id or not node_id or not restart_id:
            raise RestartRecoveryError(f"restart tag identity is incomplete: {tag_path}")
        if tag.get("status") not in {"pending", "claimed", "completed"}:
            raise RestartRecoveryError(f"restart tag status is invalid: {tag_path}")
        self._require_tag_identity(tag, graph_id, node_id, tag_path)

    def _require_tag_identity(self, tag: dict[str, Any], graph_id: str, node_id: str, tag_path: str) -> None:
        expected_name = os.path.basename(self._tag_path(graph_id, node_id))
        if os.path.basename(tag_path) != expected_name:
            raise RestartRecoveryError(f"restart tag filename does not match identity: {tag_path}")
        if str(tag.get("graph_id") or "") != graph_id or str(tag.get("node_id") or "") != node_id:
            raise RestartRecoveryError(f"restart tag filename collision: {tag_path}")

    def _restart_dir(self) -> str:
        cache_dir = self._cache_dir_override or get_workspace_cache_dir()
        return os.path.join(cache_dir, RESTART_CACHE_DIRNAME)

    def _graphs_dir(self) -> str:
        return self._graphs_dir_override or runtime_paths._get_graphs_dir()

    def _lock_path(self) -> str:
        return os.path.join(self._restart_dir(), RESTART_LOCK_FILENAME)

    def _tag_path(self, graph_id: str, node_id: str) -> str:
        filename = f"{self._filename_component(graph_id)}_{self._filename_component(node_id)}.json"
        return os.path.join(self._restart_dir(), filename)

    def _state_path(self, restart_id: str, graph_id: str, node_id: str) -> str:
        filename = f"{restart_id}_{self._filename_component(graph_id)}_{self._filename_component(node_id)}.json"
        return os.path.join(self._restart_dir(), RESTART_STATE_DIRNAME, filename)

    def _resolve_state_path(self, tag: dict[str, Any]) -> str:
        relative = str(tag.get("state_path") or "").strip().replace("/", os.sep)
        if not relative:
            raise RestartRecoveryError("restart tag state_path is required")
        return self._resolve_inside(self._restart_dir(), relative, "restart state path")

    def _config_path_from_relative(self, relative: str) -> str:
        return self._resolve_inside(self._graphs_dir(), relative.replace("/", os.sep), "node config path")

    @staticmethod
    def _resolve_inside(root: str, relative: str, label: str) -> str:
        root_path = os.path.realpath(root)
        target = os.path.realpath(os.path.join(root_path, relative))
        try:
            common = os.path.commonpath([os.path.normcase(root_path), os.path.normcase(target)])
        except ValueError as exc:
            raise RestartRecoveryError(f"{label} escapes its root") from exc
        if common != os.path.normcase(root_path):
            raise RestartRecoveryError(f"{label} escapes its root")
        return target

    @staticmethod
    def _filename_component(value: object) -> str:
        text = str(value or "").strip()
        safe = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", text).rstrip(". ").strip()
        if not safe:
            raise RestartRecoveryError("restart tag identity component is empty")
        return safe

    @staticmethod
    def _read_json_object(path: str, *, required: bool) -> dict[str, Any]:
        if not os.path.isfile(path):
            if required:
                raise RestartRecoveryError(f"restart recovery file not found: {path}")
            return {}
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise RestartRecoveryError(f"restart recovery file must contain an object: {path}")
        return payload

    @staticmethod
    def _write_json(path: str, payload: dict[str, Any]) -> None:
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    @staticmethod
    def _validate_json_payload(payload: dict[str, Any]) -> None:
        json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _remove_file(path: str) -> None:
        if path and os.path.isfile(path):
            os.remove(path)

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="microseconds")


__all__ = [
    "RESTART_RECOVERY_SCHEMA_VERSION",
    "RestartRecoveryCoordinator",
    "RestartRecoveryError",
]
