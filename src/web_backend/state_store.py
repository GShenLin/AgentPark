import json
import os
import threading
from datetime import datetime

from .node_config_service import read_node_config_optional, write_node_config
from .node_event_sequence import bump_node_event_seq
from .node_state_machine import (
    apply_recovery_plan,
    parse_node_state,
    plan_stale_working_recovery,
    plan_startup_recovery,
)
from .runtime_event_store import append_runtime_event
from .runtime_event_store import clear_runtime_event


def _preview_text(value: object, limit: int = 260) -> str:
    raw = "" if value is None else str(value)
    compact = raw.replace("\r", " ").replace("\n", " ")
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "…"


def _append_jsonl_line(file_path: str, payload: dict) -> None:
    if not file_path:
        return
    try:
        parent = os.path.dirname(file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return


class NodeDeletingError(RuntimeError):
    pass


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

    def update_state(self, config_path: str, state: str) -> None:
        if not config_path:
            return
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return
            if bool(payload.get("_delete_requested")):
                return
            next_state = parse_node_state(state)
            if parse_node_state(payload.get("state")) != next_state:
                bump_node_event_seq(payload)
            payload["state"] = next_state
            if next_state != "working":
                payload.pop("_stop_requested", None)
            self._write_unlocked(config_path, payload)

    def transition_to_idle(self, config_path: str) -> None:
        if not config_path:
            return
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return
            if bool(payload.get("_delete_requested")):
                if parse_node_state(payload.get("state")) != "stop":
                    bump_node_event_seq(payload)
                payload["state"] = "stop"
                payload.pop("_stop_requested", None)
                self._write_unlocked(config_path, payload)
                return
            if parse_node_state(payload.get("state")) == "stop":
                return
            if str(payload.get("type_id") or "").strip() == "clock_node" and bool(payload.get("_clock_running")):
                if parse_node_state(payload.get("state")) != "working":
                    bump_node_event_seq(payload)
                payload["state"] = "working"
            else:
                if parse_node_state(payload.get("state")) != "idle":
                    bump_node_event_seq(payload)
                payload["state"] = "idle"
                payload.pop("_stop_requested", None)
            self._write_unlocked(config_path, payload)

    def append_pending(self, config_path: str, item: dict) -> None:
        if not config_path:
            return
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict):
                payload = {}
            if bool(payload.get("_delete_requested")):
                raise NodeDeletingError("node is being deleted")
            pending = payload.get("pending")
            if not isinstance(pending, list):
                pending = []
            pending.append(item if isinstance(item, dict) else {})
            payload["pending"] = pending
            payload["pending_count"] = len(pending)
            bump_node_event_seq(payload)
            self._write_unlocked(config_path, payload)

    def pop_pending(self, config_path: str) -> dict | None:
        if not config_path:
            return None
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return None
            pending = payload.get("pending")
            if not isinstance(pending, list) or not pending:
                pending_count_raw = payload.get("pending_count")
                pending_count = int(pending_count_raw) if isinstance(pending_count_raw, (int, float)) else 0
                if pending_count != 0:
                    payload["pending_count"] = 0
                    self._write_unlocked(config_path, payload)
                return None
            item = pending.pop(0)
            payload["pending"] = pending
            payload["pending_count"] = len(pending)
            bump_node_event_seq(payload)
            self._write_unlocked(config_path, payload)
            return item if isinstance(item, dict) else None

    def cancel_work(self, config_path: str) -> dict:
        result = {"cleared_pending": 0, "cleared_inflight": False, "state": "idle"}
        if not config_path:
            return result
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return result
            if bool(payload.get("_delete_requested")):
                result["state"] = parse_node_state(payload.get("state"))
                return result
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
            self._write_unlocked(config_path, payload)
            return result

    def is_stop_requested(self, config_path: str) -> bool:
        if not config_path:
            return False
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return False
            return bool(payload.get("_stop_requested"))

    def finish_stop_requested(self, config_path: str, message: str = "Stopped.") -> bool:
        if not config_path:
            return False
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return False
            if not bool(payload.get("_stop_requested")):
                return False
            pending = payload.get("pending")
            payload["pending_count"] = len(pending) if isinstance(pending, list) else 0
            payload.pop("inflight", None)
            payload.pop("inflight_at", None)
            payload.pop("_stop_requested", None)
            payload["state"] = "idle"
            payload["last_message"] = str(message or "Stopped.")
            payload["last_run_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            clear_runtime_event(payload)
            bump_node_event_seq(payload)
            self._write_unlocked(config_path, payload)
            return True

    def dequeue_pending_to_working(self, config_path: str, runtime_owner_id: str | None = None) -> dict | None:
        if not config_path:
            return None
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return None
            if bool(payload.get("_delete_requested")):
                return None
            current_state = parse_node_state(payload.get("state"))
            if current_state != "idle":
                is_clock_waiting = (
                    current_state == "working"
                    and str(payload.get("type_id") or "").strip() == "clock_node"
                    and bool(payload.get("_clock_running"))
                    and not isinstance(payload.get("inflight"), dict)
                )
                if not is_clock_waiting:
                    return None
            pending = payload.get("pending")
            if not isinstance(pending, list) or not pending:
                pending_count_raw = payload.get("pending_count")
                pending_count = int(pending_count_raw) if isinstance(pending_count_raw, (int, float)) else 0
                if pending_count != 0:
                    payload["pending_count"] = 0
                    self._write_unlocked(config_path, payload)
                return None
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
                return None
            item = pending.pop(picked_index)
            picked = item if isinstance(item, dict) else None
            if picked is None:
                payload["pending"] = pending
                payload["pending_count"] = len(pending)
                self._write_unlocked(config_path, payload)
                return None
            payload["pending"] = pending
            payload["pending_count"] = len(pending)
            payload["inflight"] = picked
            payload["inflight_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            payload["state"] = "working"
            bump_node_event_seq(payload)
            self._write_unlocked(config_path, payload)
            return picked

    def mark_delete_requested(self, config_path: str) -> dict:
        result = {"cleared_pending": 0, "cleared_inflight": False, "state": "stop"}
        if not config_path:
            return result
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return result
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
            self._write_unlocked(config_path, payload)
            return result

    def set_last_message(self, config_path: str, output: str) -> None:
        if not config_path:
            return
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return
            payload["last_message"] = str(output or "")
            bump_node_event_seq(payload)
            self._write_unlocked(config_path, payload)

    def set_runtime_event(self, config_path: str, event: dict | None, *, reset_history: bool = False) -> None:
        if not config_path:
            return
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return
            if isinstance(event, dict) and event:
                if reset_history:
                    clear_runtime_event(payload, reset_history=True)
                append_runtime_event(payload, event)
            else:
                clear_runtime_event(payload, reset_history=reset_history)
            bump_node_event_seq(payload)
            self._write_unlocked(config_path, payload)

    def touch_last_run_at(self, config_path: str, run_at: str | None = None) -> None:
        if not config_path:
            return
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return
            timestamp = str(run_at or "").strip() or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            payload["last_run_at"] = timestamp
            self._write_unlocked(config_path, payload)

    def set_inflight(self, config_path: str, item: dict | None) -> None:
        if not config_path:
            return
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return
            if isinstance(item, dict):
                payload["inflight"] = item
                payload["inflight_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            else:
                payload.pop("inflight", None)
                payload.pop("inflight_at", None)
            bump_node_event_seq(payload)
            self._write_unlocked(config_path, payload)

    def recover_inflight_to_pending(self, config_path: str) -> bool:
        if not config_path:
            return False
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return False
            inflight = payload.get("inflight")
            if not isinstance(inflight, dict):
                payload.pop("inflight", None)
                self._write_unlocked(config_path, payload)
                return False
            pending = payload.get("pending")
            if not isinstance(pending, list):
                pending = []
            pending.insert(0, inflight)
            payload["pending"] = pending
            payload["pending_count"] = len(pending)
            payload.pop("inflight", None)
            payload.pop("inflight_at", None)
            bump_node_event_seq(payload)
            self._write_unlocked(config_path, payload)
            return True

    def recover_startup_runtime_state(self, config_path: str) -> dict:
        result = {
            "recovered": False,
            "reason": "",
            "before_state": "idle",
            "after_state": "idle",
            "inflight_requeued": False,
            "pending_count": 0,
        }
        if not config_path:
            return result
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return result
            before_state = parse_node_state(payload.get("state"))
            plan = plan_startup_recovery(payload)
            apply_recovery_plan(payload, plan)
            if plan.changed:
                bump_node_event_seq(payload)
                self._write_unlocked(config_path, payload)
            next_result = plan.to_result()
            next_result["before_state"] = before_state
            next_result["after_state"] = parse_node_state(payload.get("state"))
            return next_result

    def recover_stale_working(self, config_path: str, stale_seconds: int = 120) -> dict:
        result = {"recovered": False, "reason": "", "pending_count": 0}
        if not config_path:
            return result
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return result
            plan = plan_stale_working_recovery(payload)
            if plan.changed:
                apply_recovery_plan(payload, plan)
                bump_node_event_seq(payload)
                self._write_unlocked(config_path, payload)
            return {
                "recovered": plan.changed,
                "reason": plan.reason if plan.changed else "",
                "pending_count": plan.pending_count,
            }


_NODE_CONFIG_STORE = NodeConfigStore()


def _read_json_dict(file_path: str) -> dict:
    return _NODE_CONFIG_STORE.read(file_path)


def _write_json_dict(file_path: str, data: dict) -> bool:
    return _NODE_CONFIG_STORE.write(file_path, data)


def _update_node_config_state(config_path: str, state: str) -> None:
    _NODE_CONFIG_STORE.update_state(config_path, state)


def _transition_node_config_to_idle(config_path: str) -> None:
    _NODE_CONFIG_STORE.transition_to_idle(config_path)


def _append_node_pending(config_path: str, item: dict) -> None:
    _NODE_CONFIG_STORE.append_pending(config_path, item)


def _pop_node_pending(config_path: str) -> dict | None:
    return _NODE_CONFIG_STORE.pop_pending(config_path)


def _cancel_node_work(config_path: str) -> dict:
    return _NODE_CONFIG_STORE.cancel_work(config_path)


def _mark_node_delete_requested(config_path: str) -> dict:
    return _NODE_CONFIG_STORE.mark_delete_requested(config_path)


def _is_node_stop_requested(config_path: str) -> bool:
    return _NODE_CONFIG_STORE.is_stop_requested(config_path)


def _finish_node_stop_requested(config_path: str, message: str = "Stopped.") -> bool:
    return _NODE_CONFIG_STORE.finish_stop_requested(config_path, message=message)


def _dequeue_node_pending_to_working(config_path: str, runtime_owner_id: str | None = None) -> dict | None:
    return _NODE_CONFIG_STORE.dequeue_pending_to_working(config_path, runtime_owner_id=runtime_owner_id)


def _set_node_config_last_message(config_path: str, output: str) -> None:
    _NODE_CONFIG_STORE.set_last_message(config_path, output)


def _set_node_config_runtime_event(config_path: str, event: dict | None, *, reset_history: bool = False) -> None:
    _NODE_CONFIG_STORE.set_runtime_event(config_path, event, reset_history=reset_history)


def _touch_node_config_last_run_at(config_path: str, run_at: str | None = None) -> None:
    _NODE_CONFIG_STORE.touch_last_run_at(config_path, run_at)


def _set_node_config_inflight(config_path: str, item: dict | None) -> None:
    _NODE_CONFIG_STORE.set_inflight(config_path, item)


def _recover_node_config_inflight(config_path: str) -> bool:
    return _NODE_CONFIG_STORE.recover_inflight_to_pending(config_path)


def _recover_node_config_startup_state(config_path: str) -> dict:
    return _NODE_CONFIG_STORE.recover_startup_runtime_state(config_path)


def _recover_node_config_stale_working(config_path: str, stale_seconds: int = 120) -> dict:
    return _NODE_CONFIG_STORE.recover_stale_working(config_path, stale_seconds=stale_seconds)
