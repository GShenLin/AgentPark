from __future__ import annotations

import os
import subprocess


class MemoryMaintenanceError(RuntimeError):
    pass


def run_memory_maintenance(
    *,
    script_path: str,
    workspace_root: str,
    memories_root: str,
    timeout_seconds: int = 120,
) -> dict:
    resolved_script = os.path.abspath(script_path)
    if not os.path.isfile(resolved_script):
        raise FileNotFoundError(resolved_script)

    command = (
        ["cmd.exe", "/c", resolved_script, "--root", os.path.abspath(memories_root)]
        if os.name == "nt"
        else [resolved_script, "--root", os.path.abspath(memories_root)]
    )
    try:
        completed = subprocess.run(
            command,
            cwd=os.path.abspath(workspace_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise MemoryMaintenanceError(f"{os.path.basename(resolved_script)} timed out") from exc
    except OSError as exc:
        raise MemoryMaintenanceError(f"failed to run {os.path.basename(resolved_script)}: {exc}") from exc

    stdout = str(completed.stdout or "").strip()
    stderr = str(completed.stderr or "").strip()
    if completed.returncode != 0:
        detail = stderr or stdout or f"exit code {completed.returncode}"
        raise MemoryMaintenanceError(f"{os.path.basename(resolved_script)} failed: {detail}")

    return {
        "ok": True,
        "returncode": completed.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }
