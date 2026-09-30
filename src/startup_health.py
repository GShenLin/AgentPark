"""Standard-library-only readiness check, usable before the application imports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
from src.providers.curl_transport import CurlHttpTransport, CurlTransportError


def probe_server(root: Path, expected_pid: int) -> dict:
    identity = json.loads((root / ".runtime" / "agentpark-server.pid").read_text(encoding="utf-8"))
    if identity.get("pid") != expected_pid or identity.get("app") != "AgentPark":
        raise ValueError("Server PID file does not identify the newly launched process.")
    if Path(identity["workspace_root"]).resolve() != root.resolve():
        raise ValueError("Server PID file belongs to another workspace.")
    host = identity["host"]
    host = "127.0.0.1" if host == "0.0.0.0" else "::1" if host == "::" else host
    authority = f"[{host}]" if ":" in host else host
    url = f"http://{authority}:{int(identity['port'])}/api/system/status"
    response = CurlHttpTransport().request(url=url, timeout_sec=2, trust_env=False).raise_for_status()
    status = response.json()
    if status.get("ok") is not True or status.get("pid") != expected_pid:
        raise ValueError("HTTP status does not identify the newly launched server.")
    if not isinstance(status.get("instance_id"), str) or not status["instance_id"]:
        raise ValueError("HTTP status has no server instance ID.")
    return status


def wait_for_server(root: Path, expected_pid: int, timeout: float = 90) -> dict:
    deadline = time.monotonic() + timeout
    last_error = "Server has not reported readiness."
    while time.monotonic() < deadline:
        try:
            return probe_server(root, expected_pid)
        except (OSError, ValueError, KeyError, TypeError, CurlTransportError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.5)
    raise TimeoutError(f"AgentPark did not become ready within {timeout:g}s. Last probe: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--process-file", required=True, type=Path)
    args = parser.parse_args()
    try:
        pid = int(args.process_file.read_text(encoding="utf-8-sig").strip())
        status = wait_for_server(args.workspace_root, pid)
        print(f"[INFO] AgentPark server ready: PID={pid}, instance={status['instance_id']}", flush=True)
        return 0
    except Exception as exc:
        print(f"[ERROR] Startup readiness failed: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
