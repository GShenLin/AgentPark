import threading
import time
import uuid
from datetime import datetime

from src.clock_config import parse_clock_interval_seconds
from src.value_parsing import parse_bool_value, parse_int_value

from .clock_runtime import CLOCK_NEXT_FIRE_AT_KEY
from .clock_runtime import CLOCK_REMAINING_KEY
from .clock_runtime import CLOCK_RUNNING_KEY
from .clock_runtime import CLOCK_TRIGGER_COUNT_KEY
from .clock_runtime import format_clock_countdown
from . import runtime_paths, state_store
from .graph_schedule_registration import ScheduleRegistrationMixin
from .node_state_machine import parse_node_state
from .runtime_state_memory_store import runtime_state_memory_store
from .scheduled_node_registry import ScheduledNodeRegistration
from .service_host import HostBoundService
from .shared import _append_node_pending, build_text_envelope

class GraphTimerScheduler(ScheduleRegistrationMixin, HostBoundService):
    _OUTPUT_KEYS = ("OutputText", "output_text")
    _CLOCK_LOOP_KEYS = ("IsLoop", "is_loop")
    _CLOCK_LOOP_COUNT_KEYS = ("LoopCount", "loop_count")
    _CLOCK_RUNNING_KEY = CLOCK_RUNNING_KEY
    _CLOCK_NEXT_FIRE_AT_KEY = CLOCK_NEXT_FIRE_AT_KEY
    _CLOCK_REMAINING_KEY = CLOCK_REMAINING_KEY
    _CLOCK_TRIGGER_COUNT_KEY = CLOCK_TRIGGER_COUNT_KEY

    def _read_output_text(self, cfg: dict) -> str:
        for key in self._OUTPUT_KEYS:
            value = cfg.get(key)
            if value is not None:
                return str(value)
        return ""

    def _enqueue_scheduled_trigger(
        self,
        *,
        graph_id: str,
        node_id: str,
        config_path: str,
        payload_text: str,
        source: str,
        event_name: str,
        log_fields: dict | None = None,
    ) -> None:
        item = {
            "payload": build_text_envelope(payload_text, role="user"),
            "depth": 0,
            "visited": [],
            "trace_id": uuid.uuid4().hex,
            "from": node_id,
            "source": source,
            "_runtime_owner_id": getattr(self.core, "runtime_owner_id", ""),
        }
        _append_node_pending(config_path, item)
        self._ensure_graph_runner(graph_id)
        self._wake_graph_runner(graph_id)

        fields = {
            "node_id": node_id,
            "payload_preview": state_store._preview_text(payload_text),
        }
        if isinstance(log_fields, dict):
            fields.update(log_fields)
        self._log_graph_event(graph_id, event_name, **fields)

    def _parse_clock_loop_enabled(self, cfg: dict) -> bool:
        if not isinstance(cfg, dict):
            return True
        raw_value = None
        for key in self._CLOCK_LOOP_KEYS:
            value = cfg.get(key)
            if value is not None:
                raw_value = value
                break
        return parse_bool_value(
            raw_value,
            default=True,
            true_values=("true", "1", "yes", "on", "enabled"),
            false_values=("false", "0", "no", "off", "disabled"),
        )

    def _parse_clock_loop_count(self, cfg: dict) -> int:
        if not isinstance(cfg, dict):
            return 0
        raw_value = None
        for key in self._CLOCK_LOOP_COUNT_KEYS:
            value = cfg.get(key)
            if value is not None:
                raw_value = value
                break
        return parse_int_value(raw_value, default=0, minimum=0)

    def _merge_clock_fields(self, config_path: str, cfg: dict, fields: dict[str, object]) -> None:
        def mutate(payload: dict) -> None:
            payload.update(fields)

        runtime_state_memory_store.update(config_path, mutate)
        if isinstance(cfg, dict):
            cfg.update(fields)
        self._scheduled_node_config_cache().invalidate(config_path)

    def _format_clock_countdown(self, remaining_seconds: int) -> str:
        return format_clock_countdown(remaining_seconds)

    def _handle_timer_trigger(
        self,
        *,
        graph_id: str,
        node_id: str,
        config_path: str,
        cfg: dict,
        now_dt: datetime,
        minute_key: str,
    ) -> int:
        if not self._is_timer_trigger_due(cfg, now_dt):
            return 0

        dedupe_key = f"{graph_id}:{node_id}:{minute_key}"
        if self.timer_trigger_last_fired.get(dedupe_key) == minute_key:
            return 0

        self._enqueue_scheduled_trigger(
            graph_id=graph_id,
            node_id=node_id,
            config_path=config_path,
            payload_text=self._read_output_text(cfg),
            source="timer_trigger",
            event_name="timer_trigger_enqueued",
            log_fields={"schedule_at": str(cfg.get("ScheduleAt") or cfg.get("schedule_at") or "")},
        )
        self.timer_trigger_last_fired[dedupe_key] = minute_key
        return 1

    def _handle_clock_trigger(
        self,
        *,
        graph_id: str,
        node_id: str,
        config_path: str,
        cfg: dict,
        now_ts: float,
    ) -> int:
        if not bool(cfg.get(self._CLOCK_RUNNING_KEY)):
            return 0
        interval_seconds = parse_clock_interval_seconds(cfg)
        if interval_seconds <= 0:
            return 0
        loop_enabled = self._parse_clock_loop_enabled(cfg)
        loop_count = self._parse_clock_loop_count(cfg)
        trigger_count_raw = cfg.get(self._CLOCK_TRIGGER_COUNT_KEY)
        try:
            trigger_count = int(float(trigger_count_raw))
        except Exception:
            trigger_count = 0

        next_fire_at = self._read_clock_next_fire_at(cfg)
        if next_fire_at is None:
            next_fire_at = now_ts + float(interval_seconds)
            remaining_seconds = interval_seconds
            self._merge_clock_fields(
                config_path,
                cfg,
                {
                    self._CLOCK_NEXT_FIRE_AT_KEY: next_fire_at,
                    self._CLOCK_REMAINING_KEY: remaining_seconds,
                    "last_message": self._format_clock_countdown(remaining_seconds),
                    "state": "working",
                },
            )
            return 0

        if now_ts < next_fire_at:
            return 0

        self._enqueue_scheduled_trigger(
            graph_id=graph_id,
            node_id=node_id,
            config_path=config_path,
            payload_text=self._read_output_text(cfg),
            source="clock_trigger",
            event_name="clock_trigger_enqueued",
            log_fields={"interval_seconds": interval_seconds, "trigger_count": trigger_count + 1},
        )
        next_trigger_count = trigger_count + 1
        should_continue = False
        if loop_enabled:
            should_continue = loop_count <= 0 or next_trigger_count < loop_count
        fields: dict[str, object] = {
            self._CLOCK_TRIGGER_COUNT_KEY: next_trigger_count,
        }
        if should_continue:
            next_scheduled_at = now_ts + float(interval_seconds)
            fields.update(
                {
                    self._CLOCK_NEXT_FIRE_AT_KEY: next_scheduled_at,
                    self._CLOCK_REMAINING_KEY: interval_seconds,
                    "state": "working",
                }
            )
        else:
            fields.update(
                {
                    self._CLOCK_RUNNING_KEY: False,
                    self._CLOCK_NEXT_FIRE_AT_KEY: None,
                    self._CLOCK_REMAINING_KEY: 0,
                    "state": "idle",
                    "last_message": f"Completed: {next_trigger_count}",
                }
            )
        self._merge_clock_fields(config_path, cfg, fields)
        return 1

    def _persist_running_clock_snapshots(self) -> dict[str, int]:
        return {"saved": 0, "failed": 0}

    def _scan_and_emit_scheduled_nodes_once(self) -> int:
        now_ts = time.time()
        now_dt = datetime.fromtimestamp(now_ts)
        minute_key = now_dt.strftime("%Y-%m-%d %H:%M")
        enqueued = 0

        for snapshot in self._iter_node_configs():
            graph_id = snapshot.graph_id
            node_id = snapshot.node_id
            config_path = snapshot.config_path
            cfg = snapshot.config
            if parse_node_state(cfg.get("state")) == "stop":
                continue

            type_id = str(cfg.get("type_id") or "").strip()
            if type_id == "timer_trigger_node":
                enqueued += self._handle_timer_trigger(
                    graph_id=graph_id,
                    node_id=node_id,
                    config_path=config_path,
                    cfg=cfg,
                    now_dt=now_dt,
                    minute_key=minute_key,
                )
            elif type_id == "clock_node":
                enqueued += self._handle_clock_trigger(
                    graph_id=graph_id,
                    node_id=node_id,
                    config_path=config_path,
                    cfg=cfg,
                    now_ts=now_ts,
                )

        if len(self.timer_trigger_last_fired) > 10000:
            cutoff = now_dt.strftime("%Y-%m-%d %H")
            self.timer_trigger_last_fired = {
                key: value
                for key, value in self.timer_trigger_last_fired.items()
                if isinstance(value, str) and value.startswith(cutoff)
            }

        return enqueued
    def _handle_registered_schedule(self, entry: ScheduledNodeRegistration) -> int:
        snapshot = self._scheduled_node_config_cache().get_scheduled_config(
            entry.config_path,
            graph_id=entry.graph_id,
            fallback_node_id=entry.node_id,
            sanitize_node_id=self._sanitize_node_id,
        )
        cfg = snapshot.config if snapshot is not None else {}
        if not isinstance(cfg, dict) or not cfg:
            self._unregister_scheduled_node(entry.graph_id, entry.node_id)
            return 0
        if parse_node_state(cfg.get("state")) == "stop":
            self._unregister_scheduled_node(entry.graph_id, entry.node_id)
            return 0

        type_id = str(cfg.get("type_id") or "").strip()
        enqueued = 0
        if type_id == "timer_trigger_node":
            enqueued = self._handle_timer_trigger(
                graph_id=entry.graph_id,
                node_id=entry.node_id,
                config_path=entry.config_path,
                cfg=cfg,
                now_dt=datetime.fromtimestamp(time.time()),
                minute_key=datetime.fromtimestamp(entry.due_at).strftime("%Y-%m-%d %H:%M"),
            )
        elif type_id == "clock_node":
            enqueued = self._handle_clock_trigger(
                graph_id=entry.graph_id,
                node_id=entry.node_id,
                config_path=entry.config_path,
                cfg=cfg,
                now_ts=time.time(),
            )
            self._refresh_scheduled_node(entry.graph_id, entry.node_id, persist=False)
            return enqueued

        self._refresh_scheduled_node(entry.graph_id, entry.node_id, persist=False)
        return enqueued
    def _timer_trigger_scheduler_loop(self, stop_event: threading.Event) -> None:
        try:
            registered = self._register_all_scheduled_nodes()
            self._log_graph_event(self.default_graph_id, "timer_scheduler_registry_loaded", registered=registered)
        except Exception as exc:
            self._log_graph_event(
                self.default_graph_id,
                "timer_scheduler_registry_load_failed",
                error=f"{type(exc).__name__}: {exc}",
            )
        while not stop_event.is_set():
            due_entries = self._scheduled_node_registry().wait_for_due(stop_event)
            handled = False
            for entry in due_entries:
                if stop_event.is_set():
                    break
                try:
                    self._handle_registered_schedule(entry)
                    handled = True
                except Exception as exc:
                    self._log_graph_event(
                        entry.graph_id,
                        "scheduled_node_fire_failed",
                        node_id=entry.node_id,
                        node_type_id=entry.type_id,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    try:
                        self._refresh_scheduled_node(entry.graph_id, entry.node_id, persist=False)
                        handled = True
                    except Exception:
                        pass
            if handled:
                try:
                    self._persist_scheduled_registry()
                except Exception as exc:
                    self._log_graph_event(
                        self.default_graph_id,
                        "timer_scheduler_index_write_failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )

    def _ensure_timer_trigger_scheduler(self) -> None:
        with self.timer_scheduler_lock:
            existing = self.timer_scheduler_thread
            if isinstance(existing, threading.Thread) and existing.is_alive():
                return

            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._timer_trigger_scheduler_loop,
                args=(stop_event,),
                daemon=True,
                name="timer-trigger-scheduler",
            )
            self.timer_scheduler_stop = stop_event
            self.timer_scheduler_thread = thread
            thread.start()

    def _stop_timer_trigger_scheduler(self) -> None:
        with self.timer_scheduler_lock:
            stop_event = self.timer_scheduler_stop
            thread = self.timer_scheduler_thread
            self.timer_scheduler_stop = None
            self.timer_scheduler_thread = None
        if isinstance(stop_event, threading.Event):
            stop_event.set()
        self._scheduled_node_registry().wake()
        if isinstance(thread, threading.Thread) and thread.is_alive():
            try:
                thread.join(timeout=1.0)
            except Exception:
                pass
        self._persist_running_clock_snapshots()
