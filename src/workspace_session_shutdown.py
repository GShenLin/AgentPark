from __future__ import annotations

import os
import subprocess
import time
from typing import Any

from src.workspace_settings import get_workspace_root


def start_workspace_session_shutdown(*, reason: str, stop_timeout_seconds: int = 10) -> dict[str, Any]:
    root = os.path.abspath(get_workspace_root())
    if os.name == "nt":
        return _start_windows_workspace_session_shutdown(
            root=root,
            reason=reason,
            stop_timeout_seconds=stop_timeout_seconds,
        )
    return {"started": False, "reason": reason, "detail": "workspace session shutdown is only implemented on Windows"}


def _start_windows_workspace_session_shutdown(*, root: str, reason: str, stop_timeout_seconds: int) -> dict[str, Any]:
    script_path = os.path.join(root, "scripts", "restart_aitools.ps1")
    if not os.path.isfile(script_path):
        raise FileNotFoundError(f"workspace shutdown script not found: {script_path}")

    runtime_dir = os.path.join(root, ".runtime")
    os.makedirs(runtime_dir, exist_ok=True)
    stdout_path = os.path.join(runtime_dir, "agentpark-session-shutdown.log")
    stderr_path = os.path.join(runtime_dir, "agentpark-session-shutdown.err.log")
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(stdout_path, "a", encoding="utf-8") as handle:
        handle.write(f"[{stamp}] Starting workspace session shutdown: {reason}\n")

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    with open(stdout_path, "ab") as stdout, open(stderr_path, "ab") as stderr:
        process = subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                script_path,
                "-WorkspaceRoot",
                root,
                "-StopTimeoutSeconds",
                str(max(1, int(stop_timeout_seconds))),
            ],
            cwd=root,
            stdout=stdout,
            stderr=stderr,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )

    return {
        "started": True,
        "pid": process.pid,
        "reason": reason,
        "stdout": stdout_path,
        "stderr": stderr_path,
    }


__all__ = ["start_workspace_session_shutdown"]
