from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Sequence

from src.web_backend import runtime_paths


RESTART_EXIT_CODE = 43


@dataclass(frozen=True)
class RestartLaunch:
    script_path: str
    pid: int
    label: str = ""

    def __post_init__(self) -> None:
        if not self.label:
            object.__setattr__(self, "label", restart_script_label(self.script_path))


def resolve_restart_script(root: str | None = None) -> str:
    runtime_root = os.path.abspath(root or runtime_paths._get_runtime_root())
    script_name = "Restart.bat" if os.name == "nt" else "Restart.sh"
    script_path = os.path.join(runtime_root, script_name)
    if not os.path.isfile(script_path):
        raise FileNotFoundError(f"{script_name} does not exist: {script_path}")
    return script_path


def restart_script_label(script_path: str) -> str:
    return os.path.basename(str(script_path or "").strip()) or "restart script"


def build_restart_command(script_path: str) -> Sequence[str]:
    if os.name == "nt":
        return ["cmd.exe", "/c", script_path]
    return [script_path]


def launch_restart_script() -> RestartLaunch:
    root = runtime_paths._get_runtime_root()
    script_path = resolve_restart_script(root)
    creationflags = 0
    popen_kwargs = {}
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        popen_kwargs["creationflags"] = creationflags
    else:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        list(build_restart_command(script_path)),
        cwd=root,
        **popen_kwargs,
    )
    return RestartLaunch(script_path=script_path, pid=int(proc.pid), label=restart_script_label(script_path))


def launch_restart_bat() -> RestartLaunch:
    return launch_restart_script()
