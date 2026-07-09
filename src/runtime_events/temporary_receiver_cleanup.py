from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from src.file_transaction import KeyedTransactionQueue, atomic_write_text, run_with_interprocess_lock
from src.operational_memory import load_operational_memory, record_operational_memory_entry
from src.web_backend.node_config_service import node_config_service
from src.web_backend.node_memory_store import append_node_memory_entry_once, load_recent_node_memory_records
from src.web_backend.node_memory_records import read_jsonl_records
from src.web_backend.node_state_machine import parse_node_state
from src.web_backend.shared import build_text_envelope


MERGE_STATE_FILENAME = ".runtime_event_merge.json"


class TemporaryReceiverCleanup:
    def __init__(self, core: object, metrics: object | None = None) -> None:
        self.core = core
        self.metrics = metrics
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="runtime-event-cleanup")
        self._target_queue = KeyedTransactionQueue()
        self._scheduled: set[str] = set()
        self._scheduled_lock = threading.Lock()

    def schedule_if_temporary(self, *, graph_id: str, node_id: str, config: dict[str, Any] | None = None) -> bool:
        cfg = config if isinstance(config, dict) else self._read_node_config(graph_id, node_id)
        meta = runtime_receiver_meta(cfg)
        if not meta:
            return False
        key = f"{graph_id}/{node_id}"
        with self._scheduled_lock:
            if key in self._scheduled:
                return True
            self._scheduled.add(key)
        self._executor.submit(self._cleanup_scheduled, graph_id, node_id)
        return True

    def cleanup_now(self, *, graph_id: str, node_id: str) -> dict[str, Any]:
        cfg = self._read_node_config(graph_id, node_id)
        meta = runtime_receiver_meta(cfg)
        if not meta:
            return {"ok": False, "skipped": True, "reason": "not_temporary_runtime_event_receiver"}
        merge_target = meta.get("merge_target") if isinstance(meta.get("merge_target"), dict) else {}
        target_graph_id = str(merge_target.get("graph_id") or "").strip()
        target_node_id = str(merge_target.get("node_id") or "").strip()
        if not target_graph_id or not target_node_id:
            return {"ok": False, "error": "temporary receiver missing merge_target"}
        target_key = self.core.graph_runtime._node_dir(target_graph_id, target_node_id)
        return self._target_queue.run(target_key, lambda: self._merge_and_destroy(graph_id, node_id, cfg, meta))

    def clear_companion_unexecuted_inbox(self, *, graph_id: str = "Companion", node_id: str = "Companion") -> dict[str, Any]:
        config_path = self.core.graph_runtime._node_config_path(node_id, graph_id)
        if not config_path or not os.path.exists(config_path):
            return {"ok": True, "cleared": 0, "missing": True}
        cleared = 0

        def mutate(payload: dict[str, Any]) -> None:
            nonlocal cleared
            pending = payload.get("pending")
            if isinstance(pending, list):
                next_pending = [
                    item for item in pending
                    if not (isinstance(item, dict) and str(item.get("source") or "") == "runtime_event_dispatch")
                ]
                cleared = len(pending) - len(next_pending)
                payload["pending"] = next_pending
                payload["pending_count"] = len(next_pending)

        node_config_service.update(config_path, mutate, effective="immediate")
        return {"ok": True, "cleared": cleared}

    def _cleanup_scheduled(self, graph_id: str, node_id: str) -> None:
        try:
            self.cleanup_now(graph_id=graph_id, node_id=node_id)
        finally:
            with self._scheduled_lock:
                self._scheduled.discard(f"{graph_id}/{node_id}")

    def _merge_and_destroy(
        self,
        graph_id: str,
        node_id: str,
        cfg: dict[str, Any],
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        state = self._read_merge_state(graph_id, node_id)
        if state.get("status") in {"destroyed"}:
            return {"ok": True, "status": state.get("status")}

        self._write_merge_state(graph_id, node_id, {**state, "status": "merge_running", "updated_at": _now()})
        self._mark_cleanup_state(graph_id, node_id, "merge_running")
        result: dict[str, Any] = {}
        try:
            result = self._merge_into_target(graph_id, node_id, meta, state)
            self._write_merge_state(
                graph_id,
                node_id,
                {**state, **result, "status": "destroyed", "updated_at": _now()},
            )
            self._mark_cleanup_state(graph_id, node_id, "merged")
            self.core.node_ops.delete_node_instance(node_id, graph_id=graph_id)
            if self.metrics is not None and hasattr(self.metrics, "inc"):
                self.metrics.inc("temporary_receiver_destroyed")
            return {"ok": True, "status": "destroyed", **result}
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self._write_merge_state(
                graph_id,
                node_id,
                {**state, **result, "status": "merge_error", "error": error, "updated_at": _now()},
            )
            self._mark_cleanup_state(graph_id, node_id, "merge_error", error=error)
            if self.metrics is not None and hasattr(self.metrics, "inc"):
                self.metrics.inc("temporary_receiver_merge_failed")
            return {"ok": False, "status": "merge_error", "error": error}

    def _merge_into_target(
        self,
        graph_id: str,
        node_id: str,
        meta: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        merge_target = meta.get("merge_target") if isinstance(meta.get("merge_target"), dict) else {}
        target_graph_id = str(merge_target.get("graph_id") or "").strip()
        target_node_id = str(merge_target.get("node_id") or "").strip()
        if not target_graph_id or not target_node_id:
            raise ValueError("merge target is required")
        target_config_path = self.core.graph_runtime._node_config_path(target_node_id, target_graph_id)
        if not target_config_path or not os.path.exists(target_config_path):
            raise FileNotFoundError(f"merge target not found: {target_graph_id}/{target_node_id}")

        temp_memory_path = self.core.graph_runtime._node_memory_path(node_id, graph_id)
        temp_messages_path = self.core.graph_runtime._node_messages_path(node_id, graph_id)
        target_memory_path = self.core.graph_runtime._node_memory_path(target_node_id, target_graph_id)
        target_messages_path = self.core.graph_runtime._node_messages_path(target_node_id, target_graph_id)

        creation_trace_id = str(meta.get("creation_trace_id") or "").strip()
        merge_id = f"runtime-event-merge:{graph_id}:{node_id}:{creation_trace_id or node_id}"
        records_merged = bool(state.get("records_merged"))
        memories_merged = bool(state.get("operational_memory_merged"))

        if not records_merged:
            all_records = _read_temp_records(temp_messages_path)
            for record in _merge_candidate_records(graph_id, node_id, all_records):
                append_node_memory_entry_once(
                    target_memory_path,
                    target_messages_path,
                    str(record.get("role") or "system"),
                    record,
                )
            records = load_recent_node_memory_records(temp_memory_path, temp_messages_path, limit=8)
            lines = [
                "Runtime event temporary receiver completed and was merged into Companion.",
                f"Temporary receiver: {graph_id}/{node_id}",
                f"Receiver group: {meta.get('receiver_group')}",
                f"Profile: {meta.get('profile_id')}",
                f"Event: {meta.get('created_for_event')}",
                f"Trace: {creation_trace_id}",
            ]
            if records:
                lines.append("Recent temporary receiver records:")
                for record in records[-5:]:
                    text = _record_text(record)
                    if text:
                        lines.append(f"- {text[:1000]}")
            envelope = build_text_envelope("\n".join(line for line in lines if line).strip(), role="system")
            envelope["id"] = merge_id
            envelope["trace_id"] = creation_trace_id
            append_node_memory_entry_once(target_memory_path, target_messages_path, "system", envelope)
            records_merged = True

        if not memories_merged:
            temp_operational_path = os.path.join(os.path.dirname(temp_memory_path), "operational_memory.json")
            target_operational_path = os.path.join(os.path.dirname(target_memory_path), "operational_memory.json")
            temp_memory = load_operational_memory(temp_operational_path)
            for key, item in (temp_memory.get("memories") or {}).items():
                if not isinstance(item, dict) or str(item.get("status") or "active") != "active":
                    continue
                record_operational_memory_entry(
                    path=target_operational_path,
                    action="upsert",
                    reason=f"merged from temporary runtime-event receiver {graph_id}/{node_id}",
                    kind=str(item.get("kind") or "runtime_event_correction"),
                    title=str(item.get("title") or key or "Runtime event correction"),
                    lesson=str(item.get("lesson") or item.get("evidence") or "See merged runtime event receiver record."),
                    evidence=str(item.get("evidence") or f"temporary receiver {graph_id}/{node_id}, trace {creation_trace_id}"),
                    scope=item.get("scope") if isinstance(item.get("scope"), dict) else {},
                    tool_name=str(item.get("tool_name") or ""),
                    avoid=item.get("avoid") if isinstance(item.get("avoid"), list) else [],
                    prefer=item.get("prefer") if isinstance(item.get("prefer"), list) else [],
                    confidence=str(item.get("confidence") or "medium"),
                    key=str(item.get("key") or key or ""),
                )
            memories_merged = True

        return {"records_merged": records_merged, "operational_memory_merged": memories_merged}

    def _mark_cleanup_state(self, graph_id: str, node_id: str, status: str, *, error: str = "") -> None:
        config_path = self.core.graph_runtime._node_config_path(node_id, graph_id)
        if not config_path or not os.path.exists(config_path):
            return

        def mutate(payload: dict[str, Any]) -> None:
            meta = payload.get("runtime_event_receiver")
            if not isinstance(meta, dict):
                meta = {}
            else:
                meta = dict(meta)
            meta["cleanup_status"] = status
            meta["cleanup_updated_at"] = _now()
            if error:
                meta["cleanup_error"] = error
            payload["runtime_event_receiver"] = meta

        node_config_service.update(config_path, mutate, effective="immediate")

    def _read_node_config(self, graph_id: str, node_id: str) -> dict[str, Any]:
        config_path = self.core.graph_runtime._node_config_path(node_id, graph_id)
        if not config_path or not os.path.exists(config_path):
            return {}
        return node_config_service.read_optional_object(config_path)

    def _merge_state_path(self, graph_id: str, node_id: str) -> str:
        node_dir = self.core.graph_runtime._node_dir(graph_id, node_id)
        return os.path.join(node_dir, MERGE_STATE_FILENAME)

    def _read_merge_state(self, graph_id: str, node_id: str) -> dict[str, Any]:
        path = self._merge_state_path(graph_id, node_id)
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _write_merge_state(self, graph_id: str, node_id: str, payload: dict[str, Any]) -> None:
        path = self._merge_state_path(graph_id, node_id)
        run_with_interprocess_lock(
            path + ".lock",
            lambda: atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"),
        )


def runtime_receiver_meta(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(config, dict):
        return None
    meta = config.get("runtime_event_receiver")
    if not isinstance(meta, dict) or not bool(meta.get("temporary")):
        return None
    return meta


def is_completed_temporary_receiver(config: dict[str, Any] | None) -> bool:
    meta = runtime_receiver_meta(config)
    if not meta:
        return False
    return parse_node_state((config or {}).get("state")) == "idle"


def _record_text(record: dict[str, Any]) -> str:
    parts = record.get("parts") if isinstance(record, dict) else None
    if not isinstance(parts, list):
        return ""
    output: list[str] = []
    for part in parts:
        if isinstance(part, dict) and str(part.get("type") or "") == "text":
            text = str(part.get("text") or "").strip()
            if text:
                output.append(text)
    return " ".join(output).strip()


def _read_temp_records(messages_path: str) -> list[dict[str, Any]]:
    try:
        return read_jsonl_records(messages_path)
    except Exception:
        return []


def _merge_candidate_records(graph_id: str, node_id: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    dispatch_input = next(
        (
            record for record in records
            if str(record.get("role") or "").strip().lower() == "user"
            and "Runtime event dispatch." in _record_text(record)
        ),
        None,
    )
    if isinstance(dispatch_input, dict):
        candidates.append(_namespaced_record(graph_id, node_id, dispatch_input, suffix="input"))

    final_assistant = next(
        (
            record for record in reversed(records)
            if str(record.get("role") or "").strip().lower() == "assistant"
            and _record_text(record)
        ),
        None,
    )
    if isinstance(final_assistant, dict):
        candidates.append(_namespaced_record(graph_id, node_id, final_assistant, suffix="output"))
    return candidates


def _namespaced_record(graph_id: str, node_id: str, record: dict[str, Any], *, suffix: str) -> dict[str, Any]:
    output = dict(record)
    raw_id = str(record.get("id") or suffix).strip() or suffix
    output["id"] = f"runtime-event-merge-{suffix}:{graph_id}:{node_id}:{raw_id}"
    return output


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
