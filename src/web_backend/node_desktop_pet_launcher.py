from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import threading
import time
from typing import Any

from fastapi import HTTPException

from ..workspace_settings import resolve_local_client_host
from .runtime_paths import _get_runtime_root

_PROCESS_LOCK = threading.Lock()
_PROCESS_IDS: set[int] = set()


def launch_node_desktop_pet_process(graph_id: str, node_id: str, payload: dict[str, Any]) -> subprocess.Popen:
    runtime_root = _get_runtime_root()
    pet_dir = os.path.join(runtime_root, "desktop", "pet")
    package_json = os.path.join(pet_dir, "package.json")
    if not os.path.isfile(package_json):
        raise HTTPException(status_code=500, detail=f"desktop pet package not found: {package_json}")
    log_dir = os.path.join(runtime_root, ".runtime")
    os.makedirs(log_dir, exist_ok=True)
    npm_name = "npm.cmd" if os.name == "nt" else "npm"
    npm_path = shutil.which(npm_name)
    _ensure_desktop_pet_dependencies(pet_dir, npm_path, log_dir)
    electron_path = _electron_launch_path(pet_dir)

    owner_pid = str(os.getpid())
    packed_request = _pack_launch_request(
        {
            "graph_id": graph_id,
            "node_id": node_id,
            "owner_pid": owner_pid,
            "view_id": str(payload.get("view_id") or "").strip(),
            "working_path": str(payload.get("working_path") or "").strip(),
            "open_chat": bool(payload.get("open_chat")),
            "draft_prefix": str(payload.get("draft_prefix") or ""),
            "visible": True,
            "pinned": bool(payload.get("pinned")),
        }
    )
    args = [electron_path, ".", f"--agentpark-request={packed_request}"]
    view_id = str(payload.get("view_id") or "").strip()
    working_path = str(payload.get("working_path") or "").strip()
    if working_path:
        args.extend(["--working-path", working_path])

    stdout_path = os.path.join(log_dir, "agentpark-pet.log")
    stderr_path = os.path.join(log_dir, "agentpark-pet.err.log")
    debug_path = os.path.join(log_dir, "agentpark-pet-launcher.debug.jsonl")
    env = os.environ.copy()
    env["AGENTPARK_BASE_URL"] = _desktop_pet_base_url(env)
    env["AGENTPARK_OWNER_PID"] = owner_pid
    _write_debug_log(
        debug_path,
        "launch-request",
        {
            "graph_id": graph_id,
            "node_id": node_id,
            "view_id": view_id,
            "args": args,
            "cwd": pet_dir,
            "base_url": env["AGENTPARK_BASE_URL"],
            "owner_pid": owner_pid,
        },
    )

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        stdout = open(stdout_path, "ab")
        stderr = open(stderr_path, "ab")
        try:
            process = subprocess.Popen(
                args,
                cwd=pet_dir,
                env=env,
                stdout=stdout,
                stderr=stderr,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creationflags,
            )
            stdout.close()
            stderr.close()
            _write_debug_log(debug_path, "process-started", {"pid": process.pid, "args": args})
            try:
                exit_code = process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                _remember_process(process.pid)
                _write_debug_log(debug_path, "process-running", {"pid": process.pid})
                return process
            if exit_code != 0:
                detail = _read_log_tail(stderr_path) or _read_log_tail(stdout_path)
                _write_debug_log(debug_path, "process-exited-during-startup", {"pid": process.pid, "exit_code": exit_code, "detail": detail})
                raise HTTPException(
                    status_code=500,
                    detail=f"desktop pet exited during startup with code {exit_code}: {detail}" if detail else f"desktop pet exited during startup with code {exit_code}",
                )
            return process
        except Exception:
            stdout.close()
            stderr.close()
            raise
    except HTTPException:
        raise
    except Exception as exc:
        try:
            _write_debug_log(debug_path, "launch-failed", {"error": str(exc)})
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"failed to launch desktop pet: {exc}") from exc


def _desktop_pet_base_url(env: dict[str, str]) -> str:
    host = resolve_local_client_host(env.get("AGENTPARK_SERVER_HOST") or "127.0.0.1")
    port = str(env.get("AGENTPARK_SERVER_PORT") or "8766")
    return f"http://{host}:{port}"


def _pack_launch_request(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _ensure_desktop_pet_dependencies(pet_dir: str, npm_path: str | None, log_dir: str) -> None:
    electron_path = _electron_launch_path(pet_dir)
    if os.path.isfile(electron_path):
        return
    if not npm_path:
        npm_name = "npm.cmd" if os.name == "nt" else "npm"
        raise HTTPException(status_code=500, detail=f"{npm_name} not found in PATH")

    stdout_path = os.path.join(log_dir, "agentpark-pet-install.log")
    stderr_path = os.path.join(log_dir, "agentpark-pet-install.err.log")
    try:
        with open(stdout_path, "ab") as stdout, open(stderr_path, "ab") as stderr:
            completed = subprocess.run(
                [npm_path, "install"],
                cwd=pet_dir,
                stdout=stdout,
                stderr=stderr,
                stdin=subprocess.DEVNULL,
                check=False,
            )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"failed to install desktop pet dependencies: {exc}") from exc
    if completed.returncode != 0:
        detail = _read_log_tail(stderr_path) or _read_log_tail(stdout_path)
        raise HTTPException(
            status_code=500,
            detail=(
                f"desktop pet dependency install failed with code {completed.returncode}: {detail}"
                if detail
                else f"desktop pet dependency install failed with code {completed.returncode}"
            ),
        )
    if not os.path.isfile(electron_path):
        raise HTTPException(
            status_code=500,
            detail=f"desktop pet dependency install completed but electron was not found: {electron_path}",
        )


def _electron_launch_path(pet_dir: str) -> str:
    if os.name == "nt":
        return os.path.join(pet_dir, "node_modules", "electron", "dist", "electron.exe")
    return _electron_bin_path(pet_dir)


def _remember_process(pid: int) -> None:
    safe_pid = int(pid or 0)
    if safe_pid <= 0:
        return
    with _PROCESS_LOCK:
        _PROCESS_IDS.add(safe_pid)


def _write_debug_log(path: str, event: str, payload: dict[str, Any]) -> None:
    try:
        record = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "event": event,
            **payload,
        }
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        return


def terminate_registered_desktop_pet_processes(timeout_seconds: float = 2.0) -> dict[str, Any]:
    with _PROCESS_LOCK:
        process_ids = sorted(_PROCESS_IDS | _discover_desktop_pet_process_ids())
        _PROCESS_IDS.clear()
    terminated: list[int] = []
    failed: list[dict[str, Any]] = []
    for pid in process_ids:
        if os.name == "nt":
            try:
                completed = subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    timeout=max(0.5, float(timeout_seconds or 2.0)),
                    check=False,
                )
            except Exception as exc:
                failed.append({"pid": pid, "error": str(exc)})
                continue
            if completed.returncode in {0, 128, 255}:
                terminated.append(pid)
            else:
                failed.append({"pid": pid, "error": f"taskkill exited with code {completed.returncode}"})
            continue
        try:
            os.kill(pid, 15)
            terminated.append(pid)
        except ProcessLookupError:
            terminated.append(pid)
        except Exception as exc:
            failed.append({"pid": pid, "error": str(exc)})
    return {"requested": len(process_ids), "terminated": terminated, "failed": failed}


def _discover_desktop_pet_process_ids() -> set[int]:
    if os.name != "nt":
        return set()
    pet_dir = os.path.join(_get_runtime_root(), "desktop", "pet")
    escaped_pet_dir = pet_dir.replace("'", "''")
    command = (
        "$petRoot = '" + escaped_pet_dir + "'; "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -ieq 'electron.exe' -and $_.CommandLine -and "
        "$_.CommandLine.IndexOf($petRoot, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and "
        "$_.CommandLine -match '--agentpark-request=' } | "
        "ForEach-Object { $_.ProcessId }"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
            check=False,
        )
    except Exception:
        return set()
    process_ids: set[int] = set()
    for line in str(getattr(completed, "stdout", "") or "").splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid > 0:
            process_ids.add(pid)
    return process_ids


def _electron_bin_path(pet_dir: str) -> str:
    command = "electron.cmd" if os.name == "nt" else "electron"
    return os.path.join(pet_dir, "node_modules", ".bin", command)


def _read_log_tail(path: str, max_chars: int = 2000) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_chars))
            return handle.read().strip()
    except OSError:
        return ""


__all__ = ["launch_node_desktop_pet_process", "terminate_registered_desktop_pet_processes"]
