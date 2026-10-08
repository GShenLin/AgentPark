"""Cron acknowledgement wraps node execution without owning the node run loop."""
from functools import wraps
from pathlib import Path
import time

from src.cron.repository import CronRepository
from src.cron.message import run_message
from .node_config_service import node_config_service
from .node_request_tracking import find_completed_request
from .state_store import _set_node_config_inflight, _transition_node_config_to_idle


def acknowledge_cron_run(execute):
    @wraps(execute)
    def wrapped(self, **kwargs):
        pending = kwargs["pending_item"]
        if pending.get("source") != "cron":
            return execute(self, **kwargs)
        config_path = kwargs["config_path"]
        repo = CronRepository(Path(config_path).parent.parent)
        run_id = pending["trace_id"]
        run = repo.begin_run(run_id, kwargs["entry"], time.time())
        if run is None:
            # Pausing, deleting or rescheduling invalidates already queued snapshots.
            _set_node_config_inflight(config_path, None)
            _transition_node_config_to_idle(config_path)
            return None
        # The stored authorization is authoritative, even after backend restart.
        pending["_access_role"] = run["access_role"]
        pending["payload"] = run_message(run)
        try:
            result = execute(self, **kwargs)
        except BaseException as exc:
            repo.finish_run(run_id, time.time(), f"{type(exc).__name__}: {exc}")
            raise
        completion = find_completed_request(node_config_service.read_strict(config_path), run_id)
        error = None
        if completion is None:
            error = "Node execution ended without a completion record (stopped or skipped)"
        elif completion["role"] != "assistant":
            error = completion["message"] or "Node execution failed"
        repo.finish_run(run_id, time.time(), error)
        return result
    return wrapped
