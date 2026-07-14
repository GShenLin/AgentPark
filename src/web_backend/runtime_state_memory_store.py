from __future__ import annotations

import copy
import os
import threading
import time
from typing import Any, Callable

from .node_runtime_fields import RUNTIME_STATE_FIELDS


RuntimeMutation = Callable[[dict[str, Any]], None]


class RuntimeStateContractError(ValueError):
    pass


class RuntimeStateMemoryStore:
    """Process-local projection for node runtime fields.

    Runtime state is deliberately not durable. Append-only node logs remain the
    durable audit trail; this store is only the current UI/runner projection.
    """

    def __init__(self) -> None:
        self._items: dict[str, dict[str, Any]] = {}
        self._versions: dict[str, int] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _key(self, config_path: str) -> str:
        return os.path.normcase(os.path.abspath(str(config_path or "").strip()))

    def _lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def snapshot(self, config_path: str, *, include_defaults: bool = True) -> dict[str, Any]:
        key = self._key(config_path)
        lock = self._lock_for(key)
        with lock:
            payload = copy.deepcopy(self._items.get(key) or {})
        return self._with_defaults(payload) if include_defaults else payload

    def replace_from_payload(self, config_path: str, payload: dict[str, Any]) -> None:
        runtime_payload = {
            key: copy.deepcopy(value)
            for key, value in (payload or {}).items()
            if key in RUNTIME_STATE_FIELDS
        }
        self.replace(config_path, runtime_payload)

    def replace(self, config_path: str, runtime_payload: dict[str, Any]) -> None:
        key = self._key(config_path)
        lock = self._lock_for(key)
        with lock:
            self._items[key] = self._normalize(runtime_payload)
            self._touch_version(key)

    def update(self, config_path: str, mutate: RuntimeMutation) -> dict[str, Any]:
        key = self._key(config_path)
        lock = self._lock_for(key)
        with lock:
            payload = self._normalize(copy.deepcopy(self._items.get(key) or {}))
            before = copy.deepcopy(payload)
            mutate(payload)
            payload = self._normalize(payload)
            if payload != before:
                self._items[key] = payload
                self._touch_version(key)
            return copy.deepcopy(self._with_defaults(payload))

    def clear(self, config_path: str) -> None:
        key = self._key(config_path)
        lock = self._lock_for(key)
        with lock:
            if key in self._items:
                self._items.pop(key, None)
                self._touch_version(key)

    def rename(self, old_config_path: str, new_config_path: str) -> None:
        old_key = self._key(old_config_path)
        new_key = self._key(new_config_path)
        if old_key == new_key:
            return
        first, second = sorted((old_key, new_key))
        first_lock = self._lock_for(first)
        second_lock = self._lock_for(second)
        with first_lock:
            with second_lock:
                payload = self._items.pop(old_key, None)
                self._versions.pop(old_key, None)
                if payload is not None:
                    self._items[new_key] = payload
                self._touch_version(new_key)

    def version(self, config_path: str) -> int:
        key = self._key(config_path)
        lock = self._lock_for(key)
        with lock:
            return int(self._versions.get(key) or 0)

    def merge(self, config_path: str, config_payload: dict[str, Any]) -> dict[str, Any]:
        merged = {
            key: copy.deepcopy(value)
            for key, value in (config_payload or {}).items()
            if key not in RUNTIME_STATE_FIELDS
        }
        merged.update(self.snapshot(config_path))
        return merged

    def split_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        config_payload: dict[str, Any] = {}
        runtime_payload: dict[str, Any] = {}
        for key, value in (payload or {}).items():
            if key in RUNTIME_STATE_FIELDS:
                runtime_payload[key] = copy.deepcopy(value)
            else:
                config_payload[key] = copy.deepcopy(value)
        return config_payload, self._normalize(runtime_payload)

    def _normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            key: copy.deepcopy(value)
            for key, value in (payload or {}).items()
            if key in RUNTIME_STATE_FIELDS
        }
        self._normalize_state(normalized)
        self._normalize_pending(normalized)
        self._validate_optional_list(normalized, "held_outputs")
        self._validate_optional_dict(normalized, "inflight")
        self._validate_optional_dict(normalized, "last_runtime_event")
        self._validate_optional_list(normalized, "runtime_events")
        self._validate_optional_list(normalized, "runtime_tool_calls")
        self._validate_optional_list(normalized, "provider_request_summaries")
        self._validate_optional_dict(normalized, "provider_request_totals")
        self._validate_optional_list(normalized, "completed_requests")
        self._validate_optional_dict(normalized, "last_completed_request")
        self._validate_optional_dict(normalized, "goal_state")
        self._validate_optional_non_negative_int(normalized, "node_event_seq")
        return normalized

    def _with_defaults(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._normalize(dict(payload))
        result.setdefault("state", "idle")
        result.setdefault("pending_count", 0)
        return result

    def _normalize_state(self, payload: dict[str, Any]) -> None:
        if "state" not in payload:
            return
        value = payload.get("state")
        if not isinstance(value, str) or not value.strip():
            raise RuntimeStateContractError("runtime state field state must be a non-empty string")
        payload["state"] = value.strip().lower()

    def _normalize_pending(self, payload: dict[str, Any]) -> None:
        has_pending = "pending" in payload
        pending = payload.get("pending")
        if has_pending:
            if not isinstance(pending, list):
                raise RuntimeStateContractError("runtime state field pending must be a list")
            for index, item in enumerate(pending):
                if not isinstance(item, dict):
                    raise RuntimeStateContractError(f"runtime state field pending[{index}] must be an object")
            payload["pending"] = list(pending)
            payload["pending_count"] = len(pending)
            return
        if "pending_count" not in payload:
            return
        count = self._require_non_negative_int(payload.get("pending_count"), "pending_count")
        if count != 0:
            raise RuntimeStateContractError("runtime state field pending_count cannot be positive without pending")
        payload["pending_count"] = 0

    def _validate_optional_dict(self, payload: dict[str, Any], key: str) -> None:
        if key in payload and not isinstance(payload.get(key), dict):
            raise RuntimeStateContractError(f"runtime state field {key} must be an object")

    def _validate_optional_list(self, payload: dict[str, Any], key: str) -> None:
        if key in payload and not isinstance(payload.get(key), list):
            raise RuntimeStateContractError(f"runtime state field {key} must be a list")

    def _validate_optional_non_negative_int(self, payload: dict[str, Any], key: str) -> None:
        if key in payload:
            payload[key] = self._require_non_negative_int(payload.get(key), key)

    def _require_non_negative_int(self, value: Any, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RuntimeStateContractError(f"runtime state field {field_name} must be a non-negative integer")
        return value

    def _touch_version(self, key: str) -> None:
        self._versions[key] = time.time_ns()


runtime_state_memory_store = RuntimeStateMemoryStore()
