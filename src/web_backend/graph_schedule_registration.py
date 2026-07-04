import os
import time
from datetime import datetime

from src.clock_config import parse_clock_interval_seconds

from .clock_runtime import read_clock_next_fire_at
from . import runtime_paths, state_store
from .node_state_machine import parse_node_state
from .scheduled_node_config_cache import ScheduledNodeConfigCache
from .scheduled_node_index import read_schedule_index
from .scheduled_node_index import write_schedule_index
from .scheduled_node_registry import ScheduledNodeRegistration
from .scheduled_node_registry import ScheduledNodeRegistry


class ScheduleRegistrationMixin:
    def _scheduled_node_config_cache(self) -> ScheduledNodeConfigCache:
        cache = getattr(self.core, "_timer_scheduler_config_cache", None)
        if not isinstance(cache, ScheduledNodeConfigCache):
            cache = ScheduledNodeConfigCache()
            setattr(self.core, "_timer_scheduler_config_cache", cache)
        return cache

    def _scheduled_node_registry(self) -> ScheduledNodeRegistry:
        registry = getattr(self.core, "_timer_scheduler_registry", None)
        if not isinstance(registry, ScheduledNodeRegistry):
            registry = ScheduledNodeRegistry()
            setattr(self.core, "_timer_scheduler_registry", registry)
        return registry

    def _iter_node_configs(self):
        graphs_dir = runtime_paths._get_graphs_dir()
        yield from self._scheduled_node_config_cache().iter_scheduled_configs(
            graphs_dir,
            sanitize_graph_id=self._sanitize_graph_id,
            sanitize_node_id=self._sanitize_node_id,
        )

    def _read_clock_next_fire_at(self, cfg: dict) -> float | None:
        return read_clock_next_fire_at(cfg) if isinstance(cfg, dict) else None

    def _parse_timer_schedule_at(self, cfg: dict) -> datetime | None:
        if not isinstance(cfg, dict):
            return None
        schedule_raw = cfg.get("ScheduleAt")
        if schedule_raw is None:
            schedule_raw = cfg.get("schedule_at")
        schedule_text = str(schedule_raw or "").strip()
        if not schedule_text:
            return None

        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(schedule_text, fmt)
            except Exception:
                continue
        try:
            normalized = schedule_text.replace("T", " ")
            if len(normalized) == 16:
                normalized += ":00"
            return datetime.fromisoformat(normalized)
        except Exception:
            return None

    def _is_timer_trigger_due(self, cfg: dict, now_dt: datetime) -> bool:
        parsed = self._parse_timer_schedule_at(cfg)
        if parsed is None or parsed.year < 1900:
            return False
        return (
            parsed.year == now_dt.year
            and parsed.month == now_dt.month
            and parsed.day == now_dt.day
            and parsed.hour == now_dt.hour
            and parsed.minute == now_dt.minute
        )

    def _timer_schedule_due_at(self, cfg: dict, now_ts: float | None = None) -> float | None:
        parsed = self._parse_timer_schedule_at(cfg)
        if parsed is None or parsed.year < 1900:
            return None
        due_at = parsed.timestamp()
        now = time.time() if now_ts is None else float(now_ts)
        if now >= due_at + 60.0:
            return None
        if now >= due_at:
            return now
        return due_at

    def _clock_schedule_due_at(self, config_path: str, cfg: dict, now_ts: float | None = None) -> float | None:
        if not isinstance(cfg, dict) or not bool(cfg.get(self._CLOCK_RUNNING_KEY)):
            return None
        interval_seconds = parse_clock_interval_seconds(cfg)
        if interval_seconds <= 0:
            return None
        next_fire_at = self._read_clock_next_fire_at(cfg)
        if next_fire_at is None:
            now = time.time() if now_ts is None else float(now_ts)
            next_fire_at = now + float(interval_seconds)
            self._merge_clock_fields(
                config_path,
                cfg,
                {
                    self._CLOCK_NEXT_FIRE_AT_KEY: next_fire_at,
                    self._CLOCK_REMAINING_KEY: interval_seconds,
                    "last_message": self._format_clock_countdown(interval_seconds),
                    "state": "working",
                },
            )
        return next_fire_at

    def _build_scheduled_registration(
        self,
        *,
        graph_id: str,
        node_id: str,
        config_path: str,
        cfg: dict,
        now_ts: float | None = None,
    ) -> ScheduledNodeRegistration | None:
        if not isinstance(cfg, dict) or parse_node_state(cfg.get("state")) == "stop":
            return None
        type_id = str(cfg.get("type_id") or "").strip()
        due_at: float | None = None
        if type_id == "timer_trigger_node":
            due_at = self._timer_schedule_due_at(cfg, now_ts=now_ts)
        elif type_id == "clock_node":
            due_at = self._clock_schedule_due_at(config_path, cfg, now_ts=now_ts)
        if due_at is None:
            return None
        return ScheduledNodeRegistration(
            graph_id=self._sanitize_graph_id(graph_id),
            node_id=self._sanitize_node_id(node_id),
            config_path=config_path,
            type_id=type_id,
            due_at=float(due_at),
        )

    def _register_all_scheduled_nodes(self, *, force_rebuild: bool = False) -> int:
        if not force_rebuild:
            indexed_entries = read_schedule_index(
                sanitize_graph_id=self._sanitize_graph_id,
                sanitize_node_id=self._sanitize_node_id,
                node_config_path=self._node_config_path,
            )
            if indexed_entries is not None:
                self._scheduled_node_registry().rebuild(indexed_entries)
                return len(indexed_entries)

        now_ts = time.time()
        entries: list[ScheduledNodeRegistration] = []
        for snapshot in self._iter_node_configs():
            entry = self._build_scheduled_registration(
                graph_id=snapshot.graph_id,
                node_id=snapshot.node_id,
                config_path=snapshot.config_path,
                cfg=snapshot.config,
                now_ts=now_ts,
            )
            if entry is not None:
                entries.append(entry)
        self._scheduled_node_registry().rebuild(entries)
        self._persist_scheduled_registry()
        return len(entries)

    def _persist_scheduled_registry(self) -> None:
        write_schedule_index(self._scheduled_node_registry().snapshot())

    def _refresh_scheduled_node(self, graph_id: str, node_id: str, *, persist: bool = True) -> None:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        safe_node_id = self._sanitize_node_id(node_id)
        config_path = self._node_config_path(safe_node_id, safe_graph_id)
        if not config_path:
            self._scheduled_node_registry().unregister(safe_graph_id, safe_node_id)
            if persist:
                self._persist_scheduled_registry()
            return
        self._scheduled_node_config_cache().invalidate(config_path)
        if not os.path.exists(config_path):
            self._scheduled_node_registry().unregister(safe_graph_id, safe_node_id)
            if persist:
                self._persist_scheduled_registry()
            return
        cfg = state_store._read_json_dict(config_path)
        entry = self._build_scheduled_registration(
            graph_id=safe_graph_id,
            node_id=safe_node_id,
            config_path=config_path,
            cfg=cfg,
        )
        if entry is None:
            self._scheduled_node_registry().unregister(safe_graph_id, safe_node_id)
        else:
            self._scheduled_node_registry().register(entry)
        if persist:
            self._persist_scheduled_registry()

    def _unregister_scheduled_node(self, graph_id: str, node_id: str) -> None:
        self._scheduled_node_registry().unregister(
            self._sanitize_graph_id(graph_id),
            self._sanitize_node_id(node_id),
        )
        self._persist_scheduled_registry()

    def _unregister_scheduled_graph(self, graph_id: str) -> None:
        self._scheduled_node_registry().unregister_graph(self._sanitize_graph_id(graph_id))
        self._persist_scheduled_registry()
