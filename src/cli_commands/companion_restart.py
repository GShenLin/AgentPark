from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from src.web_backend import runtime_paths


RESTART_EXIT_CODE = 43


@dataclass(frozen=True)
class RestartLaunch:
    script_path: str
    pid: int


def launch_restart_bat() -> RestartLaunch:
    root = runtime_paths._get_runtime_root()
    script_path = os.path.join(root, "Restart.bat")
    if not os.path.isfile(script_path):
        raise FileNotFoundError(f"Restart.bat does not exist: {script_path}")
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    proc = subprocess.Popen(
        ["cmd.exe", "/c", script_path] if os.name == "nt" else [script_path],
        cwd=root,
        creationflags=creationflags,
    )
    return RestartLaunch(script_path=script_path, pid=int(proc.pid))
