import json
import os
from dataclasses import dataclass
from typing import Callable

from .node_runtime_fields import RUNTIME_STATE_FIELDS
from .runtime_state_memory_store import runtime_state_memory_store


SCHEDULED_NODE_TYPES = {"clock_node", "timer_trigger_node"}


@dataclass(frozen=True)
class ScheduledNodeConfigSnapshot:
    graph_id: str
    node_id: str
    config_path: str
    config: dict


@dataclass
class _CachedNodeConfig:
    config_mtime_ns: int
    runtime_version: int
    snapshot: ScheduledNodeConfigSnapshot | None


class ScheduledNodeConfigCache:
    """Small read-through cache for scheduler scans.

    The scheduler needs static node config plus the process-local runtime
    projection. It reads only the canonical config plus in-process runtime state.
    """

    def __init__(self) -> None:
        self._items: dict[str, _CachedNodeConfig] = {}

    def iter_scheduled_configs(
        self,
        graphs_dir: str,
        *,
        sanitize_graph_id: Callable[[object], str],
        sanitize_node_id: Callable[[object], str],
    ):
        if not graphs_dir or not os.path.isdir(graphs_dir):
            self._items.clear()
            return

        seen_paths: set[str] = set()
        for graph_entry in os.listdir(graphs_dir):
            graph_dir = os.path.join(graphs_dir, graph_entry)
            if not os.path.isdir(graph_dir):
                continue
            safe_graph_id = sanitize_graph_id(graph_entry)
            if not safe_graph_id:
                continue

            for node_entry in os.listdir(graph_dir):
                if node_entry == "agents":
                    continue
                node_dir = os.path.join(graph_dir, node_entry)
                config_path = os.path.join(node_dir, "config.json")
                if not os.path.isdir(node_dir) or not os.path.exists(config_path):
                    continue

                canonical_path = os.path.normcase(os.path.abspath(config_path))
                seen_paths.add(canonical_path)
                cached = self._read_or_get_cached(
                    config_path,
                    graph_id=safe_graph_id,
                    sanitize_node_id=sanitize_node_id,
                )
                if cached is not None:
                    yield cached

        for cached_path in list(self._items):
            if cached_path not in seen_paths:
                self._items.pop(cached_path, None)

    def invalidate(self, config_path: str) -> None:
        if not config_path:
            return
        self._items.pop(os.path.normcase(os.path.abspath(config_path)), None)

    def get_scheduled_config(
        self,
        config_path: str,
        *,
        graph_id: str,
        sanitize_node_id: Callable[[object], str],
    ) -> ScheduledNodeConfigSnapshot | None:
        if not config_path or not os.path.exists(config_path):
            return None
        return self._read_or_get_cached(
            config_path,
            graph_id=graph_id,
            sanitize_node_id=sanitize_node_id,
        )

    def _read_or_get_cached(
        self,
        config_path: str,
        *,
        graph_id: str,
        sanitize_node_id: Callable[[object], str],
    ) -> ScheduledNodeConfigSnapshot | None:
        canonical_path = os.path.normcase(os.path.abspath(config_path))
        config_mtime_ns = os.stat(config_path).st_mtime_ns
        runtime_version = runtime_state_memory_store.version(config_path)

        cached = self._items.get(canonical_path)
        if (
            cached is not None
            and cached.config_mtime_ns == config_mtime_ns
            and cached.runtime_version == runtime_version
        ):
            return cached.snapshot

        snapshot = self._read_snapshot(
            config_path,
            graph_id=graph_id,
            sanitize_node_id=sanitize_node_id,
        )
        self._items[canonical_path] = _CachedNodeConfig(
            config_mtime_ns=config_mtime_ns,
            runtime_version=runtime_version,
            snapshot=snapshot,
        )
        return snapshot

    def _read_snapshot(
        self,
        config_path: str,
        *,
        graph_id: str,
        sanitize_node_id: Callable[[object], str],
    ) -> ScheduledNodeConfigSnapshot | None:
        cfg = self._read_json_object(config_path)
        if not cfg:
            return None
        cfg = {key: value for key, value in cfg.items() if key not in RUNTIME_STATE_FIELDS}
        type_id = str(cfg.get("type_id") or "").strip()
        if type_id not in SCHEDULED_NODE_TYPES:
            return None

        runtime_cfg = runtime_state_memory_store.snapshot(config_path)
        if runtime_cfg:
            cfg = dict(cfg)
            cfg.update(runtime_cfg)
        raw_node_id = cfg.get("node_id")
        if not isinstance(raw_node_id, str) or not raw_node_id.strip():
            return None
        safe_node_id = sanitize_node_id(raw_node_id)
        if not safe_node_id:
            return None
        return ScheduledNodeConfigSnapshot(
            graph_id=graph_id,
            node_id=safe_node_id,
            config_path=config_path,
            config=cfg,
        )

    @staticmethod
    def _read_json_object(path: str) -> dict:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}
