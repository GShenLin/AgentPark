"""Backend-lifetime pump for the durable cron execution outbox."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from src.cron.repository import CronRepository
from src.cron.message import run_message
from . import runtime_paths
from .node_config_service import node_config_service

logger = logging.getLogger(__name__)


class CronService:
    def __init__(self, core):
        self.core = core
        self.stop = threading.Event()
        self.thread = None
        self.retry_at = {}

    def start(self):
        if self.thread is not None:
            raise RuntimeError("cron service is already started")
        # Recover only once per backend lifetime, never while polling live executions.
        for path in Path(runtime_paths._get_graphs_dir()).glob("*/cron.sqlite3"):
            CronRepository(path.parent).recover_interrupted()
        self.stop.clear()
        self.thread = threading.Thread(target=self._run, name="cron-scheduler", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=20)
            if self.thread.is_alive():
                raise RuntimeError("cron scheduler did not stop")
            self.thread = None

    def _run(self):
        while not self.stop.is_set():
            for path in Path(runtime_paths._get_graphs_dir()).glob("*/cron.sqlite3"):
                if self.stop.is_set():
                    break
                try:
                    self.poll_graph(path.parent)
                except Exception:
                    logger.exception("Cron polling failed: graph=%s", path.parent.name)
            self.stop.wait(1)

    def poll_graph(self, directory: Path, *, now: float | None = None):
        now = time.time() if now is None else now
        repo = CronRepository(directory)
        repo.materialize_due(now)
        for run in repo.pending_runs():
            key = (str(directory), run["id"])
            if self.stop.is_set():
                break
            if time.monotonic() < self.retry_at.get(key, 0):
                continue
            try:
                config = node_config_service.read_strict(str(directory / run["node_id"] / "config.json"))
                if config.get("type_id") != "agent_node":
                    raise ValueError("Cron target is no longer an agent_node")
                self.core.node_ops.enqueue_node_instance_pending(run["node_id"], {
                    "payload": run_message(run), "source": "cron", "trace_id": run["id"],
                    "idempotency_key": run["id"], "_access_role": run["access_role"],
                }, graph_id=directory.name)
            except Exception as exc:
                repo.delivery_error(run["id"], f"{type(exc).__name__}: {exc}")
                self.retry_at[key] = time.monotonic() + 10
                logger.exception("Cron enqueue failed: graph=%s node=%s", directory.name, run["node_id"])
            else:
                self.retry_at.pop(key, None)
                # The normal pending queue is memory-only. Acknowledge the durable
                # run only at the node execution boundary, never on enqueue.
