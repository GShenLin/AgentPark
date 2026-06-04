import os
import threading
import time

from . import runtime_paths, state_store
from .graph_runner_settings import resolve_graph_runner_worker_count
from .node_metadata_reader import NodeMetadataError
from .service_host import HostBoundService
from .shared import (
    ConfigLoader,
    _dequeue_node_pending_to_working,
    _recover_node_config_stale_working,
    _write_json_dict,
)


class GraphRunnerRuntime(HostBoundService):
    def _graph_runner_loop(self, graph_id: str, stop_event: threading.Event, wake_event: threading.Event) -> None:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        nodes_dir = runtime_paths._get_nodes_dir()
        last_nodes_dir_log = 0.0
        last_graph_dir_log = 0.0
        self._log_graph_event(safe_graph_id, "runner_start", nodes_dir=nodes_dir)
        while not stop_event.is_set():
            wake_event.wait(timeout=0.4)
            wake_event.clear()
            if stop_event.is_set():
                break
            if not nodes_dir:
                nodes_dir = runtime_paths._get_nodes_dir()
            if not nodes_dir:
                now = time.time()
                if now - last_nodes_dir_log > 5:
                    last_nodes_dir_log = now
                    self._log_graph_event(safe_graph_id, "runner_missing_nodes_dir")
                continue
            for _ in range(200):
                if stop_event.is_set():
                    break
                graph_cfg = self._read_graph_config(safe_graph_id)
                outgoing = self._build_outgoing_links_map(graph_cfg)
                base_dir = self._graph_dir(safe_graph_id)
                if not base_dir or not os.path.isdir(base_dir):
                    now = time.time()
                    if now - last_graph_dir_log > 5:
                        last_graph_dir_log = now
                        self._log_graph_event(safe_graph_id, "runner_missing_graph_dir", base_dir=base_dir)
                    break

                progressed = False
                for entry in os.listdir(base_dir):
                    if entry == "agents":
                        continue
                    config_path = os.path.join(base_dir, entry, "config.json")
                    if not os.path.isdir(os.path.join(base_dir, entry)) or not os.path.exists(config_path):
                        continue
                    cfg = state_store._read_json_dict(config_path)
                    if not isinstance(cfg, dict) or not cfg:
                        continue
                    if cfg.get("input_num") is None or cfg.get("output_num") is None:
                        type_id_for_ports = str(cfg.get("type_id") or "").strip()
                        try:
                            node_for_ports = self._load_node_instance(type_id_for_ports) if type_id_for_ports else None
                            input_num, output_num = self._read_node_ports(
                                node_for_ports,
                                {"graph_id": safe_graph_id, "node_instance_id": entry, "node_type_id": type_id_for_ports},
                            )
                            cfg["input_num"] = input_num
                            cfg["output_num"] = output_num
                            _write_json_dict(config_path, cfg)
                        except NodeMetadataError as exc:
                            self._log_graph_event(
                                safe_graph_id,
                                "node_metadata_read_failed",
                                node_instance_id=entry,
                                node_type_id=type_id_for_ports or None,
                                error=str(exc),
                            )
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
                    item = _dequeue_node_pending_to_working(config_path)
                    if not isinstance(item, dict):
                        continue
                    self._run_single_node_iteration(
                        safe_graph_id=safe_graph_id,
                        entry=entry,
                        cfg=cfg,
                        config_path=config_path,
                        pending_item=item,
                        outgoing=outgoing,
                        nodes_dir=nodes_dir,
                        wake_event=wake_event,
                    )
                    progressed = True
                    break

                if not progressed:
                    break
        self._log_graph_event(safe_graph_id, "runner_stop")

    def _ensure_graph_runner(self, graph_id: str) -> None:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        with self.graph_runners_lock:
            existing = self.graph_runners.get(safe_graph_id)
            if isinstance(existing, dict):
                threads = existing.get("threads")
                if not isinstance(threads, list):
                    legacy_thread = existing.get("thread")
                    threads = [legacy_thread] if isinstance(legacy_thread, threading.Thread) else []
                if any(isinstance(th, threading.Thread) and th.is_alive() for th in threads):
                    return

            worker_count = resolve_graph_runner_worker_count(ConfigLoader().get_config())

            stop_event = threading.Event()
            wake_event = threading.Event()
            wake_event.set()
            threads: list[threading.Thread] = []
            for i in range(worker_count):
                th = threading.Thread(
                    target=self._graph_runner_loop,
                    args=(safe_graph_id, stop_event, wake_event),
                    daemon=True,
                    name=f"graph-runner-{safe_graph_id}-{i}",
                )
                threads.append(th)
                th.start()
            self.graph_runners[safe_graph_id] = {
                "threads": threads,
                "stop": stop_event,
                "wake": wake_event,
                "worker_count": worker_count,
            }
        self._log_graph_event(safe_graph_id, "runner_thread_started", worker_count=worker_count)

    def _wake_graph_runner(self, graph_id: str) -> None:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        with self.graph_runners_lock:
            existing = self.graph_runners.get(safe_graph_id)
            wake = existing.get("wake") if isinstance(existing, dict) else None
        if isinstance(wake, threading.Event):
            wake.set()
