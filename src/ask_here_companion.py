from __future__ import annotations

import os
import subprocess
import time
from typing import Any

from src.companion_cli_window import (
    CompanionCliWindowStatus,
    get_companion_cli_window_status,
    show_companion_cli_window,
)
from src.companion_paths import companion_node_config_path
from src.web_backend import runtime_paths
from src.web_backend.node_config_service import node_config_service


DEFAULT_CLI_START_TIMEOUT_SECONDS = 180.0


def dispatch_to_companion_cli(working_path: str) -> dict[str, Any]:
    normalized_path = _normalize_working_path(working_path)
    _set_companion_working_path(normalized_path)

    status = get_companion_cli_window_status()
    if not status.running and str(os.environ.get("AGENTPARK_ASK_HERE_PROJECT_STARTING") or "") == "1":
        status = wait_for_companion_cli(timeout_seconds=30.0, required=False)

    if status.running:
        if not status.visible:
            show_companion_cli_window()
            return {
                "mode": "companion_cli_shown",
                "working_path": normalized_path,
                "pid": status.pid,
            }
        return {
            "mode": "companion_cli_path_updated",
            "working_path": normalized_path,
            "pid": status.pid,
        }

    process_id = launch_agentpark_hidden()
    status = wait_for_companion_cli(timeout_seconds=DEFAULT_CLI_START_TIMEOUT_SECONDS, required=True)
    show_companion_cli_window()
    return {
        "mode": "companion_cli_started",
        "working_path": normalized_path,
        "pid": status.pid,
        "launcher_pid": process_id,
    }


def wait_for_companion_cli(
    *,
    timeout_seconds: float,
    required: bool,
) -> CompanionCliWindowStatus:
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while time.monotonic() < deadline:
        status = get_companion_cli_window_status()
        if status.running:
            return status
        time.sleep(0.25)
    status = get_companion_cli_window_status()
    if status.running or not required:
        return status
    raise RuntimeError("build_and_run.bat started, but the Companion CLI did not become ready")


def launch_agentpark_hidden() -> int:
    if os.name != "nt":
        raise RuntimeError("hidden AgentPark startup is only supported on Windows")
    root = os.path.abspath(runtime_paths._get_runtime_root())
    launcher = os.path.join(root, "scripts", "start_agentpark_hidden.ps1")
    if not os.path.isfile(launcher):
        raise RuntimeError(f"AgentPark hidden launcher does not exist: {launcher}")
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            launcher,
            "-WorkspaceRoot",
            root,
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
        raise RuntimeError(f"failed to start build_and_run.bat: {detail}")
    try:
        process_id = int(completed.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError) as exc:
        raise RuntimeError("hidden AgentPark launcher did not return a process id") from exc
    if process_id <= 0:
        raise RuntimeError("hidden AgentPark launcher returned an invalid process id")
    return process_id


def _set_companion_working_path(working_path: str) -> None:
    config_path = companion_node_config_path(runtime_paths._get_graphs_dir())
    if not os.path.isfile(config_path):
        raise RuntimeError(f"Companion config does not exist: {config_path}")

    def mutate(config: dict[str, Any]) -> None:
        config["working_path"] = working_path

    node_config_service.update(config_path, mutate)


def _normalize_working_path(value: str) -> str:
    path = os.path.abspath(os.path.expanduser(str(value or "").strip()))
    if not os.path.isdir(path):
        raise RuntimeError(f"Companion working path is not a directory: {path}")
    return path


__all__ = [
    "dispatch_to_companion_cli",
    "launch_agentpark_hidden",
    "wait_for_companion_cli",
]
