import json
import os
import threading
from datetime import datetime

from .runtime_event_store import append_runtime_event
from .runtime_event_store import clear_runtime_event


_NODE_STATES = {"idle", "working", "stop"}


def _parse_node_state(value: object) -> str:
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate == "running":
            return "working"
        if candidate in _NODE_STATES:
            return candidate
    return "idle"


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
        if not file_path or not os.path.exists(file_path):
            return {}
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_unlocked(self, file_path: str, data: dict) -> bool:
        if not file_path:
            return False
        tmp_path = f"{file_path}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            parent = os.path.dirname(file_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, file_path)
            return True
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
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
            payload["state"] = _parse_node_state(state)
            self._write_unlocked(config_path, payload)

    def transition_to_idle(self, config_path: str) -> None:
        if not config_path:
            return
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return
            if _parse_node_state(payload.get("state")) == "stop":
                return
            if str(payload.get("type_id") or "").strip() == "clock_node" and bool(payload.get("_clock_running")):
                payload["state"] = "working"
            else:
                payload["state"] = "idle"
            self._write_unlocked(config_path, payload)

    def append_pending(self, config_path: str, item: dict) -> None:
        if not config_path:
            return
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict):
                payload = {}
            pending = payload.get("pending")
            if not isinstance(pending, list):
                pending = []
            pending.append(item if isinstance(item, dict) else {})
            payload["pending"] = pending
            payload["pending_count"] = len(pending)
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
            self._write_unlocked(config_path, payload)
            return item if isinstance(item, dict) else None

    def dequeue_pending_to_working(self, config_path: str) -> dict | None:
        if not config_path:
            return None
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return None
            current_state = _parse_node_state(payload.get("state"))
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
            item = pending.pop(0)
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
            self._write_unlocked(config_path, payload)
            return picked

    def set_last_message(self, config_path: str, output: str) -> None:
        if not config_path:
            return
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return
            payload["last_message"] = str(output or "")
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
            self._write_unlocked(config_path, payload)
            return True

    def recover_stale_working(self, config_path: str, stale_seconds: int = 120) -> dict:
        result = {"recovered": False, "reason": "", "pending_count": 0}
        if not config_path:
            return result
        lock = self._get_lock(config_path)
        with lock:
            payload = self._read_unlocked(config_path)
            if not isinstance(payload, dict) or not payload:
                return result
            if _parse_node_state(payload.get("state")) != "working":
                return result
            pending = payload.get("pending")
            pending_list = pending if isinstance(pending, list) else []
            inflight = payload.get("inflight")
            if (
                str(payload.get("type_id") or "").strip() == "clock_node"
                and bool(payload.get("_clock_running"))
                and not isinstance(inflight, dict)
            ):
                return result
            if not isinstance(inflight, dict):
                if str(payload.get("type_id") or "").strip() == "clock_node" and bool(payload.get("_clock_running")):
                    payload["state"] = "working"
                else:
                    payload["state"] = "idle"
                payload["pending_count"] = len(pending_list)
                payload.pop("inflight", None)
                payload.pop("inflight_at", None)
                self._write_unlocked(config_path, payload)
                result["recovered"] = True
                result["reason"] = "missing_inflight"
                result["pending_count"] = len(pending_list)
                return result
            return result


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


def _dequeue_node_pending_to_working(config_path: str) -> dict | None:
    return _NODE_CONFIG_STORE.dequeue_pending_to_working(config_path)


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


def _recover_node_config_stale_working(config_path: str, stale_seconds: int = 120) -> dict:
    return _NODE_CONFIG_STORE.recover_stale_working(config_path, stale_seconds=stale_seconds)
