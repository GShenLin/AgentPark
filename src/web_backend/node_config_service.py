from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from src.file_transaction import KeyedTransactionQueue, atomic_write_text

from .node_runtime_fields import RUNTIME_STATE_FIELDS, RUNTIME_STATE_FILENAME
from .node_config_errors import (
    NodeConfigFormatError,
    NodeConfigNotFoundError,
    NodeConfigReadError,
    NodeConfigWriteError,
)
from .runtime_state_memory_store import runtime_state_memory_store


CAPABILITY_FIELDS = {
    "tools": "tool",
    "mcp_servers": "mcp",
    "skills": "skill",
    "plugins": "plugin",
}
NODE_CONFIG_SCHEMA_VERSION = 1

RESERVED_NODE_CONFIG_FIELDS = {
    "schemaVersion",
    "node_id",
    "type_id",
    "name",
    "graph_id",
    "state",
    "ui",
    "pending",
    "pending_count",
    "inflight",
    "inflight_at",
    "_stop_requested",
    "schema",
    "last_message",
    "last_runtime_event",
    "runtime_events",
    "runtime_tool_calls",
    "node_event_seq",
    "last_run_at",
    "completed_requests",
    "last_completed_request",
    "input_num",
    "output_num",
}


Mutation = Callable[[dict[str, Any]], dict[str, Any] | None]


@dataclass(frozen=True)
class NodeConfigChangeResult:
    config_path: str
    before: dict[str, Any]
    after: dict[str, Any]
    changed_fields: list[str]
    effective: str = "next_agent_run"
    warnings: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.changed_fields)

    def to_payload(self) -> dict[str, Any]:
        return {
            "config_path": self.config_path,
            "before": self.before,
            "after": self.after,
            "changed_fields": self.changed_fields,
            "effective": self.effective,
            "warnings": list(self.warnings),
        }


class NodeConfigService:
    def __init__(self) -> None:
        self._queue = KeyedTransactionQueue()

    def read_strict(self, config_path: str) -> dict[str, Any]:
        path = self._normalize_config_path(config_path)
        if not os.path.isfile(path):
            raise NodeConfigNotFoundError(f"node config does not exist: {path}")
        try:
            payload = self._read_json_payload(path)
        except json.JSONDecodeError as exc:
            raise NodeConfigFormatError(
                f"node config contains invalid JSON: {path}: line {exc.lineno} column {exc.colno}: {exc.msg}"
            ) from exc
        except OSError as exc:
            raise NodeConfigReadError(f"failed to read node config {path}: {type(exc).__name__}: {exc}") from exc
        if not isinstance(payload, dict):
            raise NodeConfigFormatError(f"node config must be a JSON object: {path}")
        config_payload = self._migrate_config(payload, path)
        return runtime_state_memory_store.merge(path, config_payload)

    def read_optional_object(self, config_path: str) -> dict[str, Any]:
        path = str(config_path or "").strip()
        if not path or not os.path.isfile(path):
            return {}
        return self.read_strict(path)

    def write(self, config_path: str, payload: dict[str, Any]) -> None:
        path = self._normalize_config_path(config_path)
        if not isinstance(payload, dict):
            raise NodeConfigWriteError(f"node config payload must be an object: {path}")
        normalized = self._migrate_config(payload, path)
        config_payload, runtime_payload = runtime_state_memory_store.split_payload(normalized)
        if "schemaVersion" not in config_payload:
            config_payload["schemaVersion"] = NODE_CONFIG_SCHEMA_VERSION

        def do_write() -> None:
            try:
                current = self._read_config_payload_optional(path)
                if current != config_payload:
                    atomic_write_text(path, json.dumps(config_payload, ensure_ascii=False, indent=2) + "\n")
                runtime_state_memory_store.replace(path, runtime_payload)
            except Exception as exc:
                raise NodeConfigWriteError(
                    f"failed to write node config {path}: {type(exc).__name__}: {exc}"
                ) from exc

        self._queue.run(path, do_write)

    def update(self, config_path: str, mutate: Mutation, *, effective: str = "next_agent_run") -> NodeConfigChangeResult:
        path = self._normalize_config_path(config_path)

        def do_update() -> NodeConfigChangeResult:
            before = self.read_strict(path)
            next_cfg = dict(before)
            mutation_result = mutate(next_cfg)
            warnings: tuple[str, ...] = ()
            if isinstance(mutation_result, dict):
                supplied_warnings = mutation_result.get("warnings")
                if isinstance(supplied_warnings, list):
                    warnings = tuple(str(item) for item in supplied_warnings)
            self._validate_capability_fields(next_cfg, path)
            changed_fields = self._changed_fields(before, next_cfg)
            if changed_fields:
                self.write(path, next_cfg)
            return NodeConfigChangeResult(
                config_path=path,
                before=before,
                after=next_cfg,
                changed_fields=changed_fields,
                effective=effective,
                warnings=warnings,
            )

        return self._queue.run(path, do_update)

    def apply_webui_payload(
        self,
        config_path: str,
        payload: dict[str, Any],
        *,
        sync_ports: Callable[[str, dict[str, Any]], None] | None = None,
        init_clock: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> NodeConfigChangeResult:
        if not isinstance(payload, dict):
            raise ValueError("payload must be object")
        fields = payload.get("fields")
        if fields is not None and not isinstance(fields, dict):
            raise ValueError("fields must be object")
        clear_fields = payload.get("clear_fields")
        if clear_fields is not None and not isinstance(clear_fields, list):
            raise ValueError("clear_fields must be list")

        def mutate(next_cfg: dict[str, Any]) -> None:
            if isinstance(fields, dict):
                for key, value in fields.items():
                    if isinstance(key, str) and key.strip() and key not in RESERVED_NODE_CONFIG_FIELDS:
                        next_cfg[key] = value
            if isinstance(clear_fields, list):
                for key in clear_fields:
                    if isinstance(key, str) and key.strip() and key not in RESERVED_NODE_CONFIG_FIELDS:
                        next_cfg.pop(key, None)

            if "ui" in payload:
                ui = payload.get("ui")
                if ui is not None and not isinstance(ui, dict):
                    raise ValueError("ui must be object")
                if isinstance(ui, dict):
                    next_cfg["ui"] = self._normalize_ui(ui)

            next_cfg.pop("schema", None)
            type_id = str(next_cfg.get("type_id") or "").strip()
            if type_id == "clock_node" and init_clock is not None:
                init_clock(type_id, next_cfg)
            if type_id and sync_ports is not None:
                sync_ports(type_id, next_cfg)

        return self.update(config_path, mutate)

    def replace_node_identity(
        self,
        config_path: str,
        *,
        node_id: str,
        graph_id: str,
        name: str | None = None,
        ui: dict[str, Any] | None = None,
        reset_runtime: bool = False,
    ) -> NodeConfigChangeResult:
        def mutate(next_cfg: dict[str, Any]) -> None:
            next_cfg["node_id"] = node_id
            next_cfg["graph_id"] = graph_id
            next_cfg["name"] = name if isinstance(name, str) and name.strip() else node_id
            if isinstance(ui, dict):
                next_cfg["ui"] = self._normalize_ui(ui)
            if reset_runtime:
                for key in RUNTIME_STATE_FIELDS:
                    next_cfg.pop(key, None)
                next_cfg["state"] = "idle"

        return self.update(config_path, mutate)

    def create_or_replace(self, config_path: str, payload: dict[str, Any]) -> None:
        self._validate_capability_fields(payload, config_path)
        self.write(config_path, payload)

    def _normalize_config_path(self, config_path: str) -> str:
        path = str(config_path or "").strip()
        if not path:
            raise NodeConfigReadError("node config path is empty")
        return os.path.abspath(path)

    @staticmethod
    def runtime_state_path(config_path: str) -> str:
        path = os.path.abspath(str(config_path or "").strip())
        parent = os.path.dirname(path)
        return os.path.join(parent, RUNTIME_STATE_FILENAME)

    def _read_json_payload(self, path: str) -> Any:
        delays = (0.0, 0.01, 0.025, 0.05, 0.1)
        last_error: PermissionError | None = None
        for delay in delays:
            if delay:
                time.sleep(delay)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    return json.load(handle)
            except PermissionError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise NodeConfigReadError(f"failed to read node config {path}: no read attempt was made")

    def _read_config_payload_optional(self, path: str) -> dict[str, Any] | None:
        if not os.path.exists(path):
            return None
        try:
            payload = self._read_json_payload(path)
            if not isinstance(payload, dict):
                raise NodeConfigFormatError(f"node config must be a JSON object: {path}")
            migrated = self._migrate_config(payload, path)
            config_payload, _runtime_payload = runtime_state_memory_store.split_payload(migrated)
            if "schemaVersion" not in config_payload:
                config_payload["schemaVersion"] = NODE_CONFIG_SCHEMA_VERSION
            return config_payload
        except (json.JSONDecodeError, OSError, NodeConfigFormatError) as exc:
            raise NodeConfigReadError(
                f"failed to read existing node config before write {path}: {type(exc).__name__}: {exc}"
            ) from exc

    def _migrate_config(self, payload: dict[str, Any], config_path: str) -> dict[str, Any]:
        version = payload.get("schemaVersion")
        if version is None:
            next_payload = dict(payload)
            next_payload["schemaVersion"] = NODE_CONFIG_SCHEMA_VERSION
            return next_payload
        if isinstance(version, bool) or not isinstance(version, int):
            raise NodeConfigFormatError(f"node config schemaVersion must be an integer: {config_path}")
        if version < 1:
            raise NodeConfigFormatError(f"node config schemaVersion must be >= 1: {config_path}")
        if version > NODE_CONFIG_SCHEMA_VERSION:
            raise NodeConfigFormatError(
                f"unsupported node config schemaVersion {version}; runtime supports {NODE_CONFIG_SCHEMA_VERSION}: {config_path}"
            )
        return dict(payload)

    def _validate_capability_fields(self, config: dict[str, Any], config_path: str) -> None:
        for field in CAPABILITY_FIELDS:
            value = config.get(field)
            if value in (None, ""):
                continue
            if not isinstance(value, list):
                raise NodeConfigFormatError(f"node config field {field} must be a list: {config_path}")
            for item in value:
                if not isinstance(item, str):
                    raise NodeConfigFormatError(
                        f"node config field {field} must contain only strings: {config_path}"
                    )

    def _normalize_ui(self, ui: dict[str, Any]) -> dict[str, int]:
        x = self._finite_number(ui.get("x"))
        y = self._finite_number(ui.get("y"))
        normalized = {"x": max(0, int(round(x))), "y": max(0, int(round(y)))}
        width = ui.get("width")
        height = ui.get("height")
        if width is not None and str(width).strip():
            normalized["width"] = max(230, int(round(self._finite_number(width))))
        if height is not None and str(height).strip():
            normalized["height"] = max(250, int(round(self._finite_number(height))))
        return normalized

    def _finite_number(self, value: object) -> float:
        try:
            number = float(value or 0)
        except Exception:
            return 0.0
        return number if math.isfinite(number) else 0.0

    def _changed_fields(self, before: dict[str, Any], after: dict[str, Any]) -> list[str]:
        keys = set(before) | set(after)
        return sorted(key for key in keys if before.get(key) != after.get(key))


node_config_service = NodeConfigService()


def read_node_config_strict(config_path: str) -> dict[str, Any]:
    return node_config_service.read_strict(config_path)


def read_node_config_optional(config_path: str) -> dict[str, Any]:
    return node_config_service.read_optional_object(config_path)


def write_node_config(config_path: str, payload: dict[str, Any]) -> None:
    node_config_service.write(config_path, payload)


def node_runtime_state_path(config_path: str) -> str:
    return node_config_service.runtime_state_path(config_path)


def node_runtime_state_version(config_path: str) -> int:
    return runtime_state_memory_store.version(config_path)
