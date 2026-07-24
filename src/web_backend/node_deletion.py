from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from typing import Any

from .node_memory_store import wait_for_node_memory_idle
from .shared import _mark_node_delete_requested


class NodeDeletionBlocked(RuntimeError):
    pass


@dataclass(frozen=True)
class NodeDeletionResult:
    removed_dir: bool
    active_cancelled: int
    stopped_runs: int
    cleared_pending: int
    cleared_inflight: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "removed_memory_dir": self.removed_dir,
            "active_cancelled": self.active_cancelled,
            "stopped_runs": self.stopped_runs,
            "cleared_pending": self.cleared_pending,
            "cleared_inflight": self.cleared_inflight,
        }


def delete_node_directory(
    *,
    core: object,
    graph_runtime: object,
    graph_id: str,
    node_id: str,
    node_dir: str,
    memory_root: str,
    wait_timeout_seconds: float,
    archive_directory=None,
) -> NodeDeletionResult:
    if not node_dir:
        raise FileNotFoundError("node instance not found")
    if not graph_runtime._is_safe_subdir(memory_root, node_dir):
        raise RuntimeError("refusing to delete outside memory root")

    dir_real = os.path.realpath(node_dir)
    if not os.path.isdir(dir_real):
        raise FileNotFoundError("node instance not found")

    config_path = graph_runtime._node_config_path(node_id, graph_id)
    memory_path = graph_runtime._node_memory_path(node_id, graph_id)
    messages_path = graph_runtime._node_messages_path(node_id, graph_id)

    deletion_state = _mark_node_delete_requested(config_path) if os.path.exists(config_path) else {}
    active_cancelled = _request_active_cancellations(core, config_path)
    stopped_runs = _stop_async_runs_for_node(core, config_path)

    if not _wait_for_active_cancellations(core, config_path, wait_timeout_seconds):
        active_count = core.node_cancellations.active_count(config_path)
        raise NodeDeletionBlocked(f"node still has {active_count} active task(s)")

    wait_for_node_memory_idle(memory_path, messages_path)
    if archive_directory is None:
        _remove_tree_with_retry(dir_real)
    else:
        archive_directory(dir_real)

    return NodeDeletionResult(
        removed_dir=True,
        active_cancelled=active_cancelled,
        stopped_runs=stopped_runs,
        cleared_pending=int(deletion_state.get("cleared_pending") or 0),
        cleared_inflight=bool(deletion_state.get("cleared_inflight")),
    )


def _request_active_cancellations(core: object, config_path: str) -> int:
    if not config_path or not hasattr(core, "node_cancellations"):
        return 0
    return int(core.node_cancellations.request(config_path))


def _wait_for_active_cancellations(core: object, config_path: str, timeout_seconds: float) -> bool:
    if not config_path or not hasattr(core, "node_cancellations"):
        return True
    return bool(core.node_cancellations.wait_until_idle(config_path, timeout_seconds))


def _stop_async_runs_for_node(core: object, config_path: str) -> int:
    node_runs = getattr(core, "node_runs", None)
    if not isinstance(node_runs, dict) or not config_path:
        return 0

    target_key = _path_key(config_path)
    stopped = 0
    failures: list[str] = []
    for run_id, run in list(node_runs.items()):
        if not isinstance(run, dict):
            continue
        if _path_key(str(run.get("node_config_path") or "")) != target_key:
            continue
        if run.get("status") != "running":
            continue
        process = run.get("process")
        if process is None:
            continue
        try:
            process.terminate()
            process.join(timeout=2.0)
            if process.is_alive() and hasattr(process, "kill"):
                process.kill()
                process.join(timeout=1.0)
            if process.is_alive():
                failures.append(f"{run_id}: process did not stop")
                continue
            run["status"] = "stopped"
            stopped += 1
        except Exception as exc:
            failures.append(f"{run_id}: {type(exc).__name__}: {exc}")

    if failures:
        raise NodeDeletionBlocked("failed to stop node run(s): " + "; ".join(failures))
    return stopped


def _remove_tree_with_retry(path: str) -> None:
    delays = (0.0, 0.05, 0.1, 0.2, 0.4)
    last_error: OSError | None = None
    for index, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        try:
            shutil.rmtree(path)
            return
        except OSError as exc:
            if not _is_transient_delete_error(exc):
                raise
            last_error = exc
        if index == len(delays) - 1:
            break
    if last_error is not None:
        raise last_error


def _is_transient_delete_error(error: OSError) -> bool:
    if isinstance(error, PermissionError):
        return True
    if os.name != "nt":
        return False
    return getattr(error, "winerror", None) in {5, 32}


def _path_key(path: str) -> str:
    text = str(path or "").strip()
    if not text:
        return ""
    return os.path.normcase(os.path.abspath(text))
