import atexit
import json
import os
import sys
import time
from typing import Any

from src.workspace_settings import get_workspace_root


PID_FILE_SCHEMA_VERSION = 1
PID_FILE_APP = "AITools"
PID_FILE_KIND = "fast_api_server"


def get_runtime_state_dir(workspace_root: str | None = None) -> str:
    root = os.path.abspath(workspace_root or get_workspace_root())
    return os.path.join(root, ".runtime")


def get_server_pid_file_path(workspace_root: str | None = None) -> str:
    return os.path.join(get_runtime_state_dir(workspace_root), "aitools-server.pid")


def build_server_pid_payload(host: str, port: int, workspace_root: str | None = None) -> dict[str, Any]:
    try:
        resolved_port = int(port)
    except Exception as exc:
        raise ValueError("server pid file port must be an integer.") from exc
    if resolved_port <= 0 or resolved_port > 65535:
        raise ValueError("server pid file port must be between 1 and 65535.")

    root = os.path.abspath(workspace_root or get_workspace_root())
    return {
        "schema_version": PID_FILE_SCHEMA_VERSION,
        "app": PID_FILE_APP,
        "kind": PID_FILE_KIND,
        "pid": os.getpid(),
        "host": str(host),
        "port": resolved_port,
        "workspace_root": root,
        "executable": sys.executable,
        "argv": list(sys.argv),
        "created_at": time.time(),
    }


def write_server_pid_file(host: str, port: int, workspace_root: str | None = None) -> str:
    payload = build_server_pid_payload(host, port, workspace_root=workspace_root)
    pid_path = get_server_pid_file_path(workspace_root)
    os.makedirs(os.path.dirname(pid_path), exist_ok=True)

    tmp_path = f"{pid_path}.{os.getpid()}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp_path, pid_path)
    return pid_path


def remove_server_pid_file(pid_path: str, expected_pid: int | None = None) -> None:
    if not os.path.exists(pid_path):
        return

    if expected_pid is not None:
        with open(pid_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if int(payload.get("pid", 0)) != int(expected_pid):
            return

    os.remove(pid_path)


def install_server_pid_file(host: str, port: int, workspace_root: str | None = None) -> str:
    pid_path = write_server_pid_file(host, port, workspace_root=workspace_root)
    expected_pid = os.getpid()

    def _cleanup() -> None:
        try:
            remove_server_pid_file(pid_path, expected_pid=expected_pid)
        except Exception as exc:
            print(f"[server] failed to remove pid file {pid_path}: {exc}", file=sys.stderr)

    atexit.register(_cleanup)
    return pid_path


__all__ = [
    "PID_FILE_APP",
    "PID_FILE_KIND",
    "PID_FILE_SCHEMA_VERSION",
    "build_server_pid_payload",
    "get_runtime_state_dir",
    "get_server_pid_file_path",
    "install_server_pid_file",
    "remove_server_pid_file",
    "write_server_pid_file",
]
