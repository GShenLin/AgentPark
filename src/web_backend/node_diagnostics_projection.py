from __future__ import annotations

import json
import os
import threading
import uuid
from copy import deepcopy
from typing import Any


DIAGNOSTICS_PROJECTION_FILENAME = "runtime_projection.json"
DIAGNOSTICS_PROJECTION_FIELDS = {
    "last_runtime_event",
    "runtime_events",
    "runtime_tool_calls",
    "provider_request_summaries",
    "provider_request_totals",
    "completed_requests",
    "last_completed_request",
}


class NodeDiagnosticsProjectionError(RuntimeError):
    pass


class NodeDiagnosticsProjectionStore:
    """Durable, compact projection of node diagnostics used by UI queries."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._cache: dict[str, tuple[int, int, dict[str, Any]]] = {}

    @staticmethod
    def _path(config_path: str) -> str:
        normalized = os.path.abspath(str(config_path or "").strip())
        if not str(config_path or "").strip():
            raise NodeDiagnosticsProjectionError("config_path is required")
        return os.path.join(os.path.dirname(normalized), DIAGNOSTICS_PROJECTION_FILENAME)

    def _lock_for(self, path: str) -> threading.Lock:
        key = os.path.normcase(path)
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def read(self, config_path: str, *, fields: set[str] | None = None) -> dict[str, Any]:
        path = self._path(config_path)
        lock = self._lock_for(path)
        with lock:
            if not os.path.isfile(path):
                self._cache.pop(os.path.normcase(path), None)
                return {}
            try:
                stat = os.stat(path)
            except OSError as exc:
                raise NodeDiagnosticsProjectionError(
                    f"failed to stat node diagnostics projection {path}: {type(exc).__name__}: {exc}"
                ) from exc
            cache_key = os.path.normcase(path)
            cached = self._cache.get(cache_key)
            if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
                return self._select(cached[2], fields=fields)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                raise NodeDiagnosticsProjectionError(
                    f"failed to read node diagnostics projection {path}: {type(exc).__name__}: {exc}"
                ) from exc
        if not isinstance(payload, dict):
            raise NodeDiagnosticsProjectionError(f"node diagnostics projection must be an object: {path}")
        selected = self._select(payload)
        with lock:
            self._cache[cache_key] = (stat.st_mtime_ns, stat.st_size, selected)
        return self._select(selected, fields=fields)

    def write(self, config_path: str, runtime_state: dict[str, Any]) -> None:
        path = self._path(config_path)
        payload = self._select(runtime_state)
        lock = self._lock_for(path)
        with lock:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            temp_path = f"{path}.{uuid.uuid4().hex}.tmp"
            try:
                with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
                    json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, path)
                stat = os.stat(path)
                self._cache[os.path.normcase(path)] = (
                    stat.st_mtime_ns,
                    stat.st_size,
                    deepcopy(payload),
                )
            except (OSError, TypeError, ValueError) as exc:
                cleanup_error: OSError | None = None
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError as cleanup_exc:
                        cleanup_error = cleanup_exc
                cleanup_detail = (
                    f"; temporary file cleanup failed: {type(cleanup_error).__name__}: {cleanup_error}"
                    if cleanup_error is not None
                    else ""
                )
                raise NodeDiagnosticsProjectionError(
                    f"failed to write node diagnostics projection {path}: {type(exc).__name__}: {exc}{cleanup_detail}"
                ) from exc

    @staticmethod
    def merge_missing(target: dict[str, Any], projection: dict[str, Any]) -> dict[str, Any]:
        merged = dict(target)
        for field, value in projection.items():
            if field not in merged:
                merged[field] = deepcopy(value)
        return merged

    @staticmethod
    def _select(payload: dict[str, Any], *, fields: set[str] | None = None) -> dict[str, Any]:
        selected_fields = DIAGNOSTICS_PROJECTION_FIELDS if fields is None else DIAGNOSTICS_PROJECTION_FIELDS & fields
        return {
            key: deepcopy(value)
            for key, value in payload.items()
            if key in selected_fields
        }


node_diagnostics_projection_store = NodeDiagnosticsProjectionStore()


__all__ = [
    "DIAGNOSTICS_PROJECTION_FIELDS",
    "DIAGNOSTICS_PROJECTION_FILENAME",
    "NodeDiagnosticsProjectionError",
    "NodeDiagnosticsProjectionStore",
    "node_diagnostics_projection_store",
]
