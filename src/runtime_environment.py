"""Detect the execution host once and share its shell contract with tools."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging
import os
import shutil
import sys


@dataclass(frozen=True)
class RuntimeEnvironment:
    platform: str
    shell: str
    shell_executable: str

    @property
    def is_windows(self) -> bool:
        return self.platform == "windows"

    def variables(self) -> dict[str, str]:
        return {
            "AGENTPARK_PLATFORM": self.platform,
            "AGENTPARK_SHELL": self.shell,
            "AGENTPARK_SHELL_EXECUTABLE": self.shell_executable,
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }


def _detect_platform() -> str:
    if os.name == "nt":
        return "windows"
    if os.environ.get("TERMUX_VERSION"):
        return "termux"
    if sys.platform == "android" or hasattr(sys, "getandroidapilevel"):
        return "android"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    if os.name == "posix":
        return "posix"
    raise RuntimeError(f"Unsupported execution platform: {sys.platform}")


@lru_cache(maxsize=1)
def get_runtime_environment() -> RuntimeEnvironment:
    platform = _detect_platform()
    # Keep Windows PowerShell, including its existing command/UTF-8 semantics.
    candidate = "powershell" if platform == "windows" else str(os.environ.get("SHELL") or "sh")
    executable = shutil.which(candidate)
    if not executable:
        raise RuntimeError(f"Execution shell is unavailable: {candidate!r} on {platform}")
    shell = "powershell" if platform == "windows" else os.path.basename(executable)
    if platform != "windows" and shell not in {"sh", "bash", "dash", "zsh", "ksh"}:
        raise RuntimeError(f"Unsupported POSIX execution shell: {shell!r}")
    return RuntimeEnvironment(platform, shell, executable)


def initialize_runtime_environment() -> RuntimeEnvironment:
    # Redetect on this host instead of trusting variables inherited from another worker.
    get_runtime_environment.cache_clear()
    environment = get_runtime_environment()
    os.environ.update(environment.variables())
    logging.getLogger(__name__).info(
        "Execution environment: platform=%s shell=%s executable=%s",
        environment.platform, environment.shell, environment.shell_executable,
    )
    return environment
