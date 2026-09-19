from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from src.ask_here_companion import dispatch_to_companion_cli
from src.server_pid_file import get_server_pid_file_path
from src.workspace_settings import get_workspace_root, read_server_settings, resolve_local_client_host


DEFAULT_TIMEOUT_SECONDS = 2.0
DEBUG_LOG_NAME = "agentpark-ask-here.debug.jsonl"


class AskHereError(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open AgentPark from a folder context menu.")
    parser.add_argument("command", choices=["ping", "wait", "dispatch"])
    parser.add_argument("--path", default="")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)
    _debug_log("main-start", command=args.command, path=args.path, timeout=args.timeout)

    try:
        if args.command == "ping":
            _request_json("GET", _health_url(resolve_server_base_url()))
            _debug_log("main-success", command=args.command)
            return 0
        if args.command == "wait":
            wait_for_server(float(args.timeout))
            _debug_log("main-success", command=args.command)
            return 0
        if args.command == "dispatch":
            dispatch_folder(args.path)
            _debug_log("main-success", command=args.command)
            return 0
    except AskHereError as exc:
        _debug_log("main-ask-here-error", command=args.command, error=str(exc))
        print(f"[AskHere] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        _debug_log("main-unexpected-error", command=args.command, error=f"{type(exc).__name__}: {exc}")
        print(f"[AskHere] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 1


def wait_for_server(timeout_seconds: float) -> str:
    deadline = time.monotonic() + max(0.1, timeout_seconds)
    last_error = ""
    attempts = 0
    while time.monotonic() < deadline:
        attempts += 1
        try:
            base_url = resolve_server_base_url()
            _request_json("GET", _health_url(base_url), timeout=1.5)
            _debug_log("wait-success", base_url=base_url, attempts=attempts)
            return base_url
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.35)
    _debug_log("wait-timeout", timeout_seconds=timeout_seconds, attempts=attempts, last_error=last_error)
    raise AskHereError(f"AgentPark server did not become ready: {last_error}")


def dispatch_folder(folder_path: str) -> dict[str, Any]:
    target = _resolve_target(folder_path)
    working_path = target["working_path"] or os.path.dirname(target["path"])
    try:
        result = dispatch_to_companion_cli(working_path)
    except Exception as exc:
        raise AskHereError(f"failed to route folder to Companion CLI: {exc}") from exc
    _debug_log("dispatch-companion-cli", path=target["path"], working_path=working_path, mode=result.get("mode"))
    return {"path": target["path"], **result}


def resolve_server_base_url() -> str:
    pid_payload = _read_pid_payload()
    if pid_payload:
        base_url = _base_url_from_host_port(pid_payload.get("host"), pid_payload.get("port"))
        _debug_log("resolve-base-url", source="pid", base_url=base_url, pid=pid_payload.get("pid"))
        return base_url
    settings = read_server_settings()
    base_url = _base_url_from_host_port(settings.get("host"), settings.get("port"))
    _debug_log("resolve-base-url", source="settings", base_url=base_url)
    return base_url


def _read_pid_payload() -> dict[str, Any] | None:
    path = get_server_pid_file_path(get_workspace_root())
    if not os.path.isfile(path):
        _debug_log("pid-file-missing", path=path)
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        _debug_log("pid-file-invalid", path=path)
        return None
    if not isinstance(payload, dict):
        _debug_log("pid-file-not-object", path=path)
        return None
    if str(payload.get("app") or "") != "AgentPark" or str(payload.get("kind") or "") != "fast_api_server":
        _debug_log("pid-file-wrong-kind", path=path, app=payload.get("app"), kind=payload.get("kind"))
        return None
    payload_root = os.path.abspath(str(payload.get("workspace_root") or ""))
    expected_root = os.path.abspath(get_workspace_root())
    if os.path.normcase(payload_root) != os.path.normcase(expected_root):
        _debug_log("pid-file-wrong-root", path=path, payload_root=payload_root, expected_root=expected_root)
        return None
    try:
        pid = int(payload.get("pid") or 0)
    except Exception:
        _debug_log("pid-file-invalid-pid", path=path, pid=payload.get("pid"))
        return None
    if pid <= 0 or not _process_alive(pid):
        _debug_log("pid-file-dead-pid", path=path, pid=pid)
        return None
    return payload


def _process_alive(pid: int) -> bool:
    if os.name == "nt":
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False
    except Exception as exc:
        _debug_log("process-alive-check-failed", pid=pid, error=f"{type(exc).__name__}: {exc}")
        return False


def _windows_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    except Exception as exc:
        _debug_log("windows-process-alive-check-failed", pid=pid, error=f"{type(exc).__name__}: {exc}")
        return False


def _base_url_from_host_port(host: object, port: object) -> str:
    safe_host = resolve_local_client_host(str(host or "127.0.0.1").strip() or "127.0.0.1")
    try:
        safe_port = int(port or 0)
    except Exception as exc:
        raise AskHereError("server port must be an integer") from exc
    if safe_port <= 0 or safe_port > 65535:
        raise AskHereError("server port must be between 1 and 65535")
    return f"http://{safe_host}:{safe_port}"


def _health_url(base_url: str) -> str:
    return f"{base_url}/api/graphs"


def _request_json(method: str, url: str, payload: dict[str, Any] | None = None, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise AskHereError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise AskHereError(str(exc.reason)) from exc
    if not body.strip():
        return {}
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise AskHereError("AgentPark API response must be an object")
    return parsed


def _resolve_target(value: object) -> dict[str, str]:
    raw = str(value or "").strip()
    if not raw:
        raise AskHereError("target path is required")
    path = os.path.abspath(os.path.expanduser(raw))
    if os.path.isdir(path):
        return {"kind": "directory", "path": path, "working_path": path}
    if os.path.isfile(path):
        return {"kind": "file", "path": path, "working_path": ""}
    raise AskHereError(f"target path does not exist: {path}")


def _debug_log(event: str, **payload: Any) -> None:
    try:
        root = get_workspace_root()
        log_dir = os.path.join(root, ".runtime")
        os.makedirs(log_dir, exist_ok=True)
        record = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "event": event,
            "pid": os.getpid(),
            **payload,
        }
        with open(os.path.join(log_dir, DEBUG_LOG_NAME), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str, separators=(",", ":")) + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())
