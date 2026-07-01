import os
import threading
import time
import uuid

from . import runtime_paths, state_store
from .graph_runtime_registry import GraphConfigReadError
from .graph_runner_settings import find_deprecated_graph_runner_worker_count
from .graph_runner_state import GraphExecutionTask, GraphExecutor, GraphRunnerState
from .node_metadata_reader import NodeMetadataError
from .node_metadata_reader import load_node_instance
from .node_metadata_reader import read_node_ports
from .node_state_machine import parse_node_state
from .service_host import HostBoundService
from .shared import (
    ConfigLoader,
    _dequeue_node_pending_to_working,
    _recover_node_config_stale_working,
    _write_json_dict,
)


class GraphRunnerRuntime(HostBoundService):
    def _graph_scheduler_loop(self, graph_id: str, state: GraphRunnerState) -> None:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        observed_wake_generation = 0
        self._log_graph_event(safe_graph_id, "scheduler_start", nodes_dir=runtime_paths._get_nodes_dir())
        while not state.stop.is_set():
            observed_wake_generation = state.wake.wait(observed_wake_generation, state.stop)
            if state.stop.is_set():
                break
            self._run_scheduler_batch(safe_graph_id, state)
        self._log_graph_event(safe_graph_id, "scheduler_stop")

    def _run_scheduler_batch(self, safe_graph_id: str, state: GraphRunnerState) -> None:
        self._cleanup_finished_tasks(safe_graph_id, state)
        if state.stop.is_set():
            return
        nodes_dir = runtime_paths._get_nodes_dir()
        if not nodes_dir:
            self._set_ready_pending_count(state, 0)
            self._log_graph_event(safe_graph_id, "scheduler_missing_nodes_dir")
            return
        try:
            graph_cfg = self._read_graph_config(safe_graph_id)
        except GraphConfigReadError as exc:
            self._set_ready_pending_count(state, 0)
            self._log_graph_event(safe_graph_id, "graph_config_read_failed", error=str(exc))
            return
        outgoing = self._build_outgoing_links_map(graph_cfg)

        ready_pending_count = 0
        for entry, config_path, cfg in self._iter_node_config_entries(safe_graph_id):
            if state.stop.is_set():
                break
            cfg = self._ensure_node_runtime_ports(safe_graph_id, entry, config_path, cfg)
            if not isinstance(cfg, dict) or not cfg:
                continue
            recovered = _recover_node_config_stale_working(config_path, stale_seconds=120)
            if isinstance(recovered, dict) and recovered.get("recovered"):
                self._log_graph_event(
                    safe_graph_id,
                    "node_working_recovered",
                    node_instance_id=entry,
                    reason=str(recovered.get("reason") or ""),
                    pending_count=int(recovered.get("pending_count") or 0),
                )
                cfg = state_store._read_json_dict(config_path)
                if not isinstance(cfg, dict) or not cfg:
                    continue
            if self._ready_pending_count_for_config(cfg) <= 0:
                continue
            item = _dequeue_node_pending_to_working(
                config_path,
                runtime_owner_id=getattr(self.core, "runtime_owner_id", ""),
            )
            if not isinstance(item, dict):
                continue
            self._submit_executor_task(
                safe_graph_id=safe_graph_id,
                state=state,
                entry=entry,
                cfg=cfg,
                config_path=config_path,
                pending_item=item,
                outgoing=outgoing,
                nodes_dir=nodes_dir,
            )
        self._set_ready_pending_count(state, ready_pending_count)

    def _iter_node_config_entries(self, safe_graph_id: str):
        base_dir = self._graph_dir(safe_graph_id)
        if not base_dir or not os.path.isdir(base_dir):
            self._log_graph_event(safe_graph_id, "scheduler_missing_graph_dir", base_dir=base_dir)
            return
        for entry in os.listdir(base_dir):
            if entry == "agents":
                continue
            config_path = os.path.join(base_dir, entry, "config.json")
            if not os.path.isdir(os.path.join(base_dir, entry)) or not os.path.exists(config_path):
                continue
            cfg = state_store._read_json_dict(config_path)
            if isinstance(cfg, dict) and cfg:
                yield entry, config_path, cfg

    def _ensure_node_runtime_ports(self, safe_graph_id: str, entry: str, config_path: str, cfg: dict) -> dict:
        if cfg.get("input_num") is not None and cfg.get("output_num") is not None:
            return cfg
        type_id_for_ports = str(cfg.get("type_id") or "").strip()
        try:
            node_for_ports = load_node_instance(type_id_for_ports) if type_id_for_ports else None
            input_num, output_num = read_node_ports(
                node_for_ports,
                {"graph_id": safe_graph_id, "node_instance_id": entry, "node_type_id": type_id_for_ports},
            )
            cfg["input_num"] = input_num
            cfg["output_num"] = output_num
            _write_json_dict(config_path, cfg)
            return cfg
        except NodeMetadataError as exc:
            self._log_graph_event(
                safe_graph_id,
                "node_metadata_read_failed",
                node_instance_id=entry,
                node_type_id=type_id_for_ports or None,
                error=str(exc),
            )
            return {}

    def _ready_pending_count_for_config(self, cfg: dict) -> int:
        if bool(cfg.get("_delete_requested")):
            return 0
        state = parse_node_state(cfg.get("state"))
        clock_waiting = (
            state == "working"
            and str(cfg.get("type_id") or "").strip() == "clock_node"
            and bool(cfg.get("_clock_running"))
            and not isinstance(cfg.get("inflight"), dict)
        )
        if state != "idle" and not clock_waiting:
            return 0
        pending = cfg.get("pending")
        return len(pending) if isinstance(pending, list) else 0

    def _submit_executor_task(
        self,
        *,
        safe_graph_id: str,
        state: GraphRunnerState,
        entry: str,
        cfg: dict,
        config_path: str,
        pending_item: dict,
        outgoing: dict[str, list[dict]],
        nodes_dir: str,
    ) -> None:
        trace_id = str(pending_item.get("trace_id") or "").strip() or uuid.uuid4().hex
        pending_item["trace_id"] = trace_id
        task_id = f"{trace_id}:{entry}"
        with state.active_lock:
            if task_id in state.active_tasks:
                self._log_graph_event(
                    safe_graph_id,
                    "executor_duplicate_task_skipped",
                    trace_id=trace_id,
                    node_instance_id=entry,
                )
                return

            def run_node() -> None:
                self._run_single_node_iteration(
                    safe_graph_id=safe_graph_id,
                    entry=entry,
                    cfg=cfg,
                    config_path=config_path,
                    pending_item=pending_item,
                    outgoing=outgoing,
                    nodes_dir=nodes_dir,
                    wake_event=state.wake,
                )

            task = state.executor.submit(task_id, entry, trace_id, run_node)
            task.future.add_done_callback(lambda _future: state.wake.set())
            state.active_tasks[task_id] = task
        self._log_graph_event(
            safe_graph_id,
            "executor_task_submitted",
            trace_id=trace_id,
            node_instance_id=entry,
            active_tasks=self._active_task_count(state),
        )

    def _cleanup_finished_tasks(self, safe_graph_id: str, state: GraphRunnerState) -> None:
        finished: list[GraphExecutionTask] = []
        with state.active_lock:
            for task_id, task in list(state.active_tasks.items()):
                if task.future.done():
                    finished.append(task)
                    state.active_tasks.pop(task_id, None)
        for task in finished:
            try:
                exc = task.future.exception()
            except Exception as future_error:
                exc = future_error
            if exc is not None:
                self._log_graph_event(
                    safe_graph_id,
                    "executor_task_failed",
                    trace_id=task.trace_id,
                    node_instance_id=task.node_id,
                    error=str(exc),
                )
            else:
                self._log_graph_event(
                    safe_graph_id,
                    "executor_task_finished",
                    trace_id=task.trace_id,
                    node_instance_id=task.node_id,
                )

    def _set_ready_pending_count(self, state: GraphRunnerState, count: int) -> None:
        with state.active_lock:
            state.ready_pending_count = max(0, int(count or 0))

    def _active_task_count(self, state: GraphRunnerState) -> int:
        with state.active_lock:
            return len(state.active_tasks)

    def _ensure_graph_runner(self, graph_id: str) -> None:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        with self.graph_runners_lock:
            existing = self.graph_runners.get(safe_graph_id)
            existing_scheduler = self._runner_scheduler_thread(existing)
            if isinstance(existing_scheduler, threading.Thread) and existing_scheduler.is_alive():
                return

            stop_event = threading.Event()
            wake_signal = _GraphRunnerWakeSignal()
            wake_signal.set()
            state = GraphRunnerState(
                scheduler_thread=None,
                stop=stop_event,
                wake=wake_signal,
                executor=GraphExecutor(safe_graph_id),
            )
            scheduler_thread = threading.Thread(
                target=self._graph_scheduler_loop,
                args=(safe_graph_id, state),
                daemon=True,
                name=f"graph-scheduler-{safe_graph_id}",
            )
            state.scheduler_thread = scheduler_thread
            self.graph_runners[safe_graph_id] = state
            scheduler_thread.start()
        deprecated_workers = find_deprecated_graph_runner_worker_count(ConfigLoader().get_config())
        if deprecated_workers is not None:
            self._log_graph_event(
                safe_graph_id,
                "deprecated_graph_runner_worker_count_ignored",
                configured_value=str(deprecated_workers),
            )
        self._log_graph_event(safe_graph_id, "scheduler_thread_started")

    def _wake_graph_runner(self, graph_id: str) -> None:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        with self.graph_runners_lock:
            existing = self.graph_runners.get(safe_graph_id)
            wake = self._runner_wake_signal(existing)
        if hasattr(wake, "set"):
            wake.set()

    def _runner_wake_signal(self, runner_state) -> "_GraphRunnerWakeSignal | None":
        if isinstance(runner_state, GraphRunnerState):
            return runner_state.wake
        if isinstance(runner_state, dict):
            return runner_state.get("wake")
        return None

    def _runner_stop_event(self, runner_state) -> threading.Event | None:
        if isinstance(runner_state, GraphRunnerState):
            return runner_state.stop
        if isinstance(runner_state, dict):
            stop_event = runner_state.get("stop")
            return stop_event if isinstance(stop_event, threading.Event) else None
        return None

    def _runner_scheduler_thread(self, runner_state) -> threading.Thread | None:
        if isinstance(runner_state, GraphRunnerState):
            return runner_state.scheduler_thread
        if isinstance(runner_state, dict):
            thread = runner_state.get("scheduler_thread") or runner_state.get("thread")
            if isinstance(thread, threading.Thread):
                return thread
            threads = runner_state.get("threads")
            if isinstance(threads, list):
                return next((item for item in threads if isinstance(item, threading.Thread)), None)
        return None

    def _runner_threads(self, runner_state) -> list[threading.Thread]:
        if isinstance(runner_state, GraphRunnerState):
            threads = []
            if isinstance(runner_state.scheduler_thread, threading.Thread):
                threads.append(runner_state.scheduler_thread)
            with runner_state.active_lock:
                threads.extend(task.thread for task in runner_state.active_tasks.values())
            return threads
        if isinstance(runner_state, dict):
            threads = runner_state.get("threads")
            if isinstance(threads, list):
                return [item for item in threads if isinstance(item, threading.Thread)]
            thread = runner_state.get("thread")
            return [thread] if isinstance(thread, threading.Thread) else []
        return []

    def _runner_status(self, safe_graph_id: str) -> dict:
        with self.graph_runners_lock:
            state = self.graph_runners.get(safe_graph_id)
        scheduler_thread = self._runner_scheduler_thread(state)
        scheduler_running = isinstance(scheduler_thread, threading.Thread) and scheduler_thread.is_alive()
        if isinstance(state, GraphRunnerState):
            self._cleanup_finished_tasks(safe_graph_id, state)
            with state.active_lock:
                active_tasks = [
                    {
                        "task_id": task.task_id,
                        "node_id": task.node_id,
                        "trace_id": task.trace_id,
                        "started_at": task.started_at,
                    }
                    for task in state.active_tasks.values()
                    if not task.future.done()
                ]
                ready_pending_count = state.ready_pending_count
            return {
                "graph_id": safe_graph_id,
                "scheduler_running": scheduler_running,
                "running": scheduler_running,
                "active_tasks": active_tasks,
                "ready_pending_count": ready_pending_count,
                "running_node_count": len(active_tasks),
            }
        threads = self._runner_threads(state)
        alive_threads = [thread for thread in threads if thread.is_alive()]
        return {
            "graph_id": safe_graph_id,
            "scheduler_running": scheduler_running,
            "running": bool(alive_threads),
            "active_tasks": [],
            "ready_pending_count": 0,
            "running_node_count": len(alive_threads),
        }


class _GraphRunnerWakeSignal:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._generation = 0

    def set(self) -> None:
        with self._condition:
            self._generation += 1
            self._condition.notify_all()

    def wait(self, observed_generation: int, stop_event: threading.Event) -> int:
        with self._condition:
            while self._generation <= int(observed_generation or 0) and not stop_event.is_set():
                self._condition.wait()
            return self._generation
