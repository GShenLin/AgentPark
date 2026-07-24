from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .routing import remote_workspace_target


def dispatch_remote_workspace_tool(
    agent: object,
    tool_name: str,
    args: Any,
    *,
    timeout_seconds: float | None,
) -> tuple[bool, Any]:
    target = remote_workspace_target(agent, tool_name)
    if target is None:
        return False, None
    payload = {
        "worker_id": target.worker_id,
        "tool_name": str(tool_name),
        "arguments": args if isinstance(args, dict) else {},
        "working_path": target.working_path,
        "timeout_seconds": _request_timeout_seconds(tool_name, args, timeout_seconds),
    }
    return True, _post_internal_json("/api/remote-workers/internal/execute", payload, payload["timeout_seconds"] + 10.0)


def _request_timeout_seconds(tool_name: str, args: Any, configured: float | None) -> float:
    if configured is not None and configured > 0:
        return max(1.0, float(configured))
    if str(tool_name) == "execute_console_command" and isinstance(args, dict):
        raw = args.get("timeout_seconds")
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            parsed = 0.0
        if parsed > 0:
            return parsed
    return 3600.0


def _post_internal_json(path: str, payload: dict[str, Any], timeout: float) -> Any:
    port = str(os.environ.get("AGENTPARK_SERVER_PORT") or "8766").strip() or "8766"
    url = f"http://127.0.0.1:{port}{path}"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(2.0, float(timeout))) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Remote workspace request failed with HTTP {exc.code}: {detail}") from exc
    except OSError as exc:
        raise RuntimeError(f"Remote workspace request failed: {type(exc).__name__}: {exc}") from exc
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Remote workspace returned invalid JSON.") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("Remote workspace returned a non-object response.")
    if not decoded.get("ok"):
        raise RuntimeError(str(decoded.get("error") or "Remote workspace execution failed."))
    return decoded.get("result")
