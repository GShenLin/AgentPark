import os
import threading
from copy import deepcopy
from datetime import datetime

from .node_config_service import patch_node_config_persistent_fields, read_node_config_optional, write_node_config
from .node_diagnostics_projection import node_diagnostics_projection_store
from .node_run_terminal import NODE_RUN_SUMMARY_STAGE
from .runtime_state_memory_store import runtime_state_memory_store
from .node_event_sequence import bump_node_event_seq
from .node_state_machine import (
    apply_recovery_plan,
    parse_node_state,
    plan_stale_working_recovery,
)
from .runtime_event_store import append_runtime_event, clear_runtime_event


class NodeDeletingError(RuntimeError):
    pass


RUNTIME_EVENT_STATE_FIELDS = {
    "last_runtime_event",
    "runtime_events",
    "runtime_tool_calls",
    "provider_request_summaries",
    "provider_request_totals",
    "node_event_seq",
}


class NodeConfigStore:
    def __init__(self) -> None:
        self._path_locks: dict[str, threading.Lock] = {}
        self._path_locks_guard = threading.Lock()

    def _canonical_path(self, file_path: str) -> str:
        return os.path.normcase(os.path.abspath(file_path))

    def _get_lock(self, file_path: str) -> threading.Lock:
        key = self._canonical_path(file_path)
        with self._path_locks_guard:
            lock = self._path_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._path_locks[key] = lock
            return lock

    def _read_unlocked(self, file_path: str) -> dict:
        return read_node_config_optional(file_path)

    def _write_unlocked(self, file_path: str, data: dict) -> bool:
        if not file_path:
            return False
        try:
            write_node_config(file_path, data)
            return True
        except Exception:
            return False

    def read(self, file_path: str) -> dict:
        if not file_path:
            return {}
        lock = self._get_lock(file_path)
        with lock:
            return self._read_unlocked(file_path)

    def write(self, file_path: str, data: dict) -> bool:
        if not file_path:
            return False
        lock = self._get_lock(file_path)
        with lock:
            return self._write_unlocked(file_path, data)

    def patch_persistent_fields(self, config_path: str, fields: dict) -> dict:
        return patch_node_config_persistent_fields(config_path, fields)

    def update_state(self, config_path: str, state: str) -> None:
        def mutate(payload: dict) -> None:
            if bool(payload.get("_delete_requested")):
                return
            next_state = parse_node_state(state)
            if parse_node_state(payload.get("state")) != next_state:
                bump_node_event_seq(payload)
            payload["state"] = next_state
            if next_state != "working":
                payload.pop("_stop_requested", None)

        if config_path:
            runtime_state_memory_store.update(config_path, mutate)

    def transition_to_idle(self, config_path: str) -> None:
        if not config_path:
            return
        cfg = self._read_unlocked(config_path)
        type_id = str((cfg or {}).get("type_id") or "").strip()

        def mutate(payload: dict) -> None:
            if bool(payload.get("_delete_requested")):
                if parse_node_state(payload.get("state")) != "stop":
                    bump_node_event_seq(payload)
                payload["state"] = "stop"
                payload.pop("_stop_requested", None)
                return
            if parse_node_state(payload.get("state")) == "stop":
                return
            if type_id == "clock_node" and bool(payload.get("_clock_running")):
                if parse_node_state(payload.get("state")) != "working":
                    bump_node_event_seq(payload)
                payload["state"] = "working"
            else:
                if parse_node_state(payload.get("state")) != "idle":
                    bump_node_event_seq(payload)
                payload["state"] = "idle"
                payload.pop("_stop_requested", None)

        runtime_state_memory_store.update(config_path, mutate)

    def append_pending(self, config_path: str, item: dict) -> None:
        if not config_path:
            return
        def mutate(payload: dict) -> None:
            if bool(payload.get("_delete_requested")):
                raise NodeDeletingError("node is being deleted")
            pending = payload.get("pending")
            if pending is None:
                pending = []
            pending.append(item if isinstance(item, dict) else {})
            payload["pending"] = pending
            payload["pending_count"] = len(pending)
            bump_node_event_seq(payload)

        runtime_state_memory_store.update(config_path, mutate)

    def pop_pending(self, config_path: str) -> dict | None:
        if not config_path:
            return None
        popped: dict | None = None

        def mutate(payload: dict) -> None:
            nonlocal popped
            pending = payload.get("pending")
            if not pending:
                return
            item = pending.pop(0)
            payload["pending"] = pending
            payload["pending_count"] = len(pending)
            bump_node_event_seq(payload)
            popped = item if isinstance(item, dict) else None

        runtime_state_memory_store.update(config_path, mutate)
        return popped

    def cancel_work(self, config_path: str) -> dict:
        result = {"cleared_pending": 0, "cleared_inflight": False, "state": "idle"}
        if not config_path:
            return result
        def mutate(payload: dict) -> None:
            if bool(payload.get("_delete_requested")):
                result["state"] = parse_node_state(payload.get("state"))
                return
            pending = payload.get("pending")
            if isinstance(pending, list):
                result["cleared_pending"] = len(pending)
            payload["pending"] = []
            payload["pending_count"] = 0
            has_inflight = isinstance(payload.get("inflight"), dict)
            result["cleared_inflight"] = False
            if has_inflight:
                result["cleared_inflight"] = True
                payload["state"] = "working"
                payload["_stop_requested"] = True
                payload["last_message"] = "Stop requested. Cancelling active work."
                result["state"] = "working"
            else:
                payload.pop("inflight", None)
                payload.pop("inflight_at", None)
                payload.pop("_stop_requested", None)
                payload["state"] = "idle"
                payload["last_message"] = "Stopped. Pending work cleared."
                result["state"] = "idle"
            bump_node_event_seq(payload)

        runtime_state_memory_store.update(config_path, mutate)
        return result

    def is_stop_requested(self, config_path: str) -> bool:
        if not config_path:
            return False
        return bool(
            runtime_state_memory_store.snapshot_fields(
                config_path,
                {"_stop_requested"},
                include_defaults=False,
            ).get("_stop_requested")
        )

    def finish_stop_requested(self, config_path: str, message: str = "Stopped.") -> bool:
        if not config_path:
            return False
        finished = False

        def mutate(payload: dict) -> None:
            nonlocal finished
            if not bool(payload.get("_stop_requested")):
                return
            pending = payload.get("pending")
            payload["pending_count"] = len(pending) if pending is not None else 0
            payload.pop("inflight", None)
            payload.pop("inflight_at", None)
            payload.pop("_stop_requested", None)
            payload["state"] = "idle"
            payload["last_message"] = str(message or "Stopped.")
            payload["last_run_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            clear_runtime_event(payload)
            bump_node_event_seq(payload)
            finished = True

        runtime_state_memory_store.update(config_path, mutate)
        return finished

    def dequeue_pending_to_working(self, config_path: str, runtime_owner_id: str | None = None) -> dict | None:
        if not config_path:
            return None
        cfg = self._read_unlocked(config_path)
        type_id = str((cfg or {}).get("type_id") or "").strip()
        picked: dict | None = None

        def mutate(payload: dict) -> None:
            nonlocal picked
            if bool(payload.get("_delete_requested")):
                return
            current_state = parse_node_state(payload.get("state"))
            if current_state != "idle":
                is_clock_waiting = (
                    current_state == "working"
                    and type_id == "clock_node"
                    and bool(payload.get("_clock_running"))
                    and not isinstance(payload.get("inflight"), dict)
                )
                if not is_clock_waiting:
                    return
            pending = payload.get("pending")
            if not pending:
                return
            owner = str(runtime_owner_id or "").strip()
            picked_index = None
            for index, candidate in enumerate(pending):
                if not isinstance(candidate, dict):
                    picked_index = index
                    break
                candidate_owner = str(candidate.get("_runtime_owner_id") or "").strip()
                if not owner or not candidate_owner or candidate_owner == owner:
                    picked_index = index
                    break
            if picked_index is None:
                return
            item = pending.pop(picked_index)
            next_picked = item if isinstance(item, dict) else None
            if next_picked is None:
                payload["pending"] = pending
                payload["pending_count"] = len(pending)
                return
            payload["pending"] = pending
            payload["pending_count"] = len(pending)
            payload["inflight"] = next_picked
            payload["inflight_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            payload["state"] = "working"
            bump_node_event_seq(payload)
            picked = next_picked

        runtime_state_memory_store.update(config_path, mutate)
        return picked

    def consume_mid_turn_user_inputs(self, config_path: str, limit: int = 16) -> list[dict]:
        if not config_path:
            return []
        consumed: list[dict] = []
        max_items = max(1, int(limit or 16))

        def mutate(payload: dict) -> None:
            nonlocal consumed
            if bool(payload.get("_delete_requested")) or bool(payload.get("_stop_requested")):
                return
            if parse_node_state(payload.get("state")) != "working":
                return
            if not isinstance(payload.get("inflight"), dict):
                return
            pending = payload.get("pending")
            if not pending:
                return
            node_id = str(payload.get("node_id") or "").strip()
            remaining: list = []
            for item in pending:
                if len(consumed) < max_items and self._is_mid_turn_user_input_item(item, node_id):
                    consumed.append(item if isinstance(item, dict) else {})
                    continue
                remaining.append(item)
            if len(remaining) == len(pending):
                return
            payload["pending"] = remaining
            payload["pending_count"] = len(remaining)
            bump_node_event_seq(payload)

        runtime_state_memory_store.update(config_path, mutate)
        return consumed

    @staticmethod
    def _is_mid_turn_user_input_item(item: object, node_id: str) -> bool:
        if not isinstance(item, dict):
            return False
        if str(item.get("source") or "").strip() != "emit":
            return False
        try:
            depth = int(float(item.get("depth") or 0))
        except Exception:
            depth = 0
        if depth != 0:
            return False
        if str(item.get("link_id") or "").strip():
            return False
        from_node = str(item.get("from") or "").strip()
        if node_id and from_node and from_node != node_id:
            return False
        payload = item.get("payload")
        if not isinstance(payload, dict):
            return False
        return str(payload.get("role") or "").strip().lower() == "user"

    def mark_delete_requested(self, config_path: str) -> dict:
        result = {"cleared_pending": 0, "cleared_inflight": False, "state": "stop"}
        if not config_path:
            return result
        def mutate(payload: dict) -> None:
            pending = payload.get("pending")
            if isinstance(pending, list):
                result["cleared_pending"] = len(pending)
            has_inflight = isinstance(payload.get("inflight"), dict)
            result["cleared_inflight"] = has_inflight
            payload["pending"] = []
            payload["pending_count"] = 0
            payload["_delete_requested"] = True
            payload["last_message"] = "Delete requested. Cancelling active work."
            if has_inflight:
                payload["_stop_requested"] = True
                payload["state"] = "working"
                result["state"] = "working"
            else:
                payload.pop("_stop_requested", None)
                payload["state"] = "stop"
                result["state"] = "stop"
            bump_node_event_seq(payload)

        runtime_state_memory_store.update(config_path, mutate)
        return result

    def set_last_message(self, config_path: str, output: str) -> None:
        if not config_path:
            return
        def mutate(payload: dict) -> None:
            payload["last_message"] = str(output or "")
            bump_node_event_seq(payload)

        runtime_state_memory_store.update(config_path, mutate)

    def set_runtime_event(self, config_path: str, event: dict | None, *, reset_history: bool = False) -> None:
        if not config_path:
            return
        lock = self._get_lock(config_path)
        with lock:
            def mutate(payload: dict) -> None:
                if not reset_history:
                    missing_fields = RUNTIME_EVENT_STATE_FIELDS - payload.keys()
                    if missing_fields:
                        durable_diagnostics = node_diagnostics_projection_store.read(
                            config_path,
                            fields=set(missing_fields),
                        )
                        for field, value in durable_diagnostics.items():
                            payload[field] = deepcopy(value)
                if isinstance(event, dict) and event:
                    if reset_history:
                        clear_runtime_event(payload, reset_history=True)
                    append_runtime_event(payload, event)
                else:
                    clear_runtime_event(payload, reset_history=reset_history)
                bump_node_event_seq(payload)

            runtime_state_memory_store.update_fields(
                config_path,
                RUNTIME_EVENT_STATE_FIELDS,
                mutate,
            )
            if reset_history or self._is_terminal_runtime_event(event):
                node_diagnostics_projection_store.write(
                    config_path,
                    runtime_state_memory_store.snapshot(config_path, include_defaults=False),
                )

    @staticmethod
    def _is_terminal_runtime_event(event: object) -> bool:
        if not isinstance(event, dict):
            return False
        return (
            str(event.get("type") or "").strip().lower() == "runtime_notice"
            and str(event.get("stage") or "").strip() == NODE_RUN_SUMMARY_STAGE
        )

    def touch_last_run_at(self, config_path: str, run_at: str | None = None) -> None:
        if not config_path:
            return
        def mutate(payload: dict) -> None:
            timestamp = str(run_at or "").strip() or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            payload["last_run_at"] = timestamp

        runtime_state_memory_store.update(config_path, mutate)

    def set_inflight(self, config_path: str, item: dict | None) -> None:
        if not config_path:
            return
        def mutate(payload: dict) -> None:
            if isinstance(item, dict):
                payload["inflight"] = item
                payload["inflight_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            else:
                payload.pop("inflight", None)
                payload.pop("inflight_at", None)
            bump_node_event_seq(payload)

        runtime_state_memory_store.update(config_path, mutate)

    def recover_inflight_to_pending(self, config_path: str) -> bool:
        if not config_path:
            return False
        recovered = False

        def mutate(payload: dict) -> None:
            nonlocal recovered
            inflight = payload.get("inflight")
            if not isinstance(inflight, dict):
                payload.pop("inflight", None)
                return
            pending = payload.get("pending")
            if pending is None:
                pending = []
            pending.insert(0, inflight)
            payload["pending"] = pending
            payload["pending_count"] = len(pending)
            payload.pop("inflight", None)
            payload.pop("inflight_at", None)
            bump_node_event_seq(payload)
            recovered = True

        runtime_state_memory_store.update(config_path, mutate)
        return recovered

    def recover_startup_runtime_state(self, config_path: str) -> dict:
        runtime_state_memory_store.clear(config_path)
        return {
            "recovered": False,
            "reason": "runtime_state_memory_reset",
            "before_state": "idle",
            "after_state": "idle",
            "inflight_requeued": False,
            "pending_count": 0,
        }

    def recover_stale_working(self, config_path: str, stale_seconds: int = 120) -> dict:
        result = {"recovered": False, "reason": "", "pending_count": 0}
        if not config_path:
            return result
        cfg = self._read_unlocked(config_path)
        type_id = str((cfg or {}).get("type_id") or "").strip()

        def mutate(payload: dict) -> None:
            if type_id and "type_id" not in payload:
                payload["type_id"] = type_id
            plan = plan_stale_working_recovery(payload)
            if plan.changed:
                apply_recovery_plan(payload, plan)
                bump_node_event_seq(payload)
            result.update(
                {
                    "recovered": plan.changed,
                    "reason": plan.reason if plan.changed else "",
                    "pending_count": plan.pending_count,
                }
            )
            payload.pop("type_id", None)

        runtime_state_memory_store.update(config_path, mutate)
        return result

