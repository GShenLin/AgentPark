from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time

# Keep these in sync with src/server_pid_file.py. This script must stay
# standalone (it runs before `pip install -e .`), so it cannot import src.*.
PID_FILE_NAME = "agentpark-server.pid"
PID_FILE_APP = "AgentPark"
PID_FILE_KIND = "fast_api_server"


def _pid_path(workspace_root: str) -> str:
    return os.path.join(os.path.abspath(workspace_root), ".runtime", PID_FILE_NAME)


def _read_payload(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("pid file payload must be a JSON object")
    return payload


def _payload_pid(payload: dict) -> int:
    return int(payload.get("pid") or 0)


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _cmdline_path(pid: int) -> str:
    return os.path.join("/proc", str(pid), "cmdline")


def _read_process_cmdline(pid: int) -> list[str]:
    try:
        with open(_cmdline_path(pid), "rb") as handle:
            raw = handle.read()
    except FileNotFoundError:
        return []
    parts = [item.decode("utf-8", errors="replace") for item in raw.split(b"\0") if item]
    return parts


def _is_expected_server_process(pid: int, payload: dict, workspace_root: str) -> bool:
    if not _process_exists(pid):
        return False

    if payload.get("app") != PID_FILE_APP or payload.get("kind") != PID_FILE_KIND:
        return False

    cmdline = _read_process_cmdline(pid)
    if not cmdline:
        return False

    normalized_root = os.path.abspath(workspace_root)
    payload_root = os.path.abspath(str(payload.get("workspace_root") or normalized_root))
    if payload_root != normalized_root:
        return False

    joined = "\0".join(cmdline)
    has_fast_api_module = "\0-m\0src.fast_api" in joined or any(part.endswith("src/fast_api.py") for part in cmdline)
    has_workspace_arg = normalized_root in cmdline or f"--workspace-root\0{normalized_root}" in joined
    return has_fast_api_module and has_workspace_arg


def _terminate(pid: int, timeout: float) -> bool:
    if not _process_exists(pid):
        return True
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            return True
        time.sleep(0.05)
    if _process_exists(pid):
        os.kill(pid, signal.SIGKILL)
    return not _process_exists(pid)


def stop_workspace_server(workspace_root: str, timeout: float) -> int:
    path = _pid_path(workspace_root)
    if not os.path.isfile(path):
        print(f"[INFO] No server pid file found: {path}")
        return 0
    try:
        payload = _read_payload(path)
        pid = _payload_pid(payload)
    except Exception as exc:
        print(f"[ERROR] Failed to read pid file {path}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if pid <= 0:
        print(f"[ERROR] Invalid pid in {path}: {pid}", file=sys.stderr)
        return 1
    if not _is_expected_server_process(pid, payload, workspace_root):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        print(f"[INFO] Removed stale server pid file: {path}")
        return 0
    if not _terminate(pid, timeout):
        print(f"[ERROR] Failed to stop server process pid={pid}", file=sys.stderr)
        return 1
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    print(f"[INFO] Stopped server process pid={pid}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", default=os.getcwd())
    parser.add_argument("--stop-only", action="store_true")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args(argv)
    if not args.stop_only:
        parser.error("only --stop-only is supported")
    return stop_workspace_server(args.workspace_root, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
