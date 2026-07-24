from __future__ import annotations

from dataclasses import dataclass
import os

from src.task_direction_store import clear_task_direction_states

from .node_memory_store import clear_node_memory
from .state_store import _cancel_node_work


class NodeMemoryResetBlocked(RuntimeError):
    """Raised when active node work cannot be stopped safely before reset."""


class NodeMemoryResetError(RuntimeError):
    """Raised when task-scoped state cannot be removed after work stops."""


@dataclass(frozen=True)
class NodeMemoryResetResult:
    cleared_file_count: int
    cleared_task_direction_files: tuple[str, ...]
    active_runs_cancelled: int
    async_runs_stopped: int
    pending_items_cleared: int


def reset_node_memory(
    *,
    core: object,
    config_path: str,
    memory_path: str,
    messages_path: str,
    node_directory: str,
    wait_timeout_seconds: float = 5.0,
) -> NodeMemoryResetResult:
    cancel_result = _cancel_node_work(config_path)
    cancellation_registry = getattr(core, "node_cancellations", None)
    active_runs_cancelled = (
        int(cancellation_registry.request(config_path))
        if cancellation_registry is not None
        else 0
    )
    async_runs_stopped = _stop_async_runs(core, config_path)
    if cancellation_registry is not None and not cancellation_registry.wait_until_idle(
        config_path,
        wait_timeout_seconds,
    ):
        active_count = int(cancellation_registry.active_count(config_path))
        raise NodeMemoryResetBlocked(
            f"node still has {active_count} active run(s); memory was not cleared"
        )

    cleared_file_count = clear_node_memory(memory_path, messages_path)
    try:
        cleared_task_files = clear_task_direction_states(node_directory)
    except OSError as exc:
        raise NodeMemoryResetError(
            f"failed to clear task direction state: {type(exc).__name__}: {exc}"
        ) from exc
    return NodeMemoryResetResult(
        cleared_file_count=int(cleared_file_count),
        cleared_task_direction_files=tuple(cleared_task_files),
        active_runs_cancelled=active_runs_cancelled,
        async_runs_stopped=async_runs_stopped,
        pending_items_cleared=int(cancel_result.get("cleared_pending") or 0),
    )


def _stop_async_runs(core: object, config_path: str) -> int:
    node_runs = getattr(core, "node_runs", None)
    if not isinstance(node_runs, dict):
        return 0
    target_path = _path_key(config_path)
    stopped = 0
    failures: list[str] = []
    for run_id, run in list(node_runs.items()):
        if not isinstance(run, dict) or run.get("status") != "running":
            continue
        if _path_key(str(run.get("node_config_path") or "")) != target_path:
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
        raise NodeMemoryResetBlocked("failed to stop node run(s): " + "; ".join(failures))
    return stopped


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(str(path or "")))
