from __future__ import annotations

from src.providers.curl_transport import CurlHttpTransport, CurlHttpError, CurlTransportError
import json
import os
import uuid
from typing import Any

from src.runtime_cancellation import raise_if_cancel_requested
from src.runtime_cancellation import register_cancel_callback

from .routing import remote_workspace_target


def dispatch_remote_workspace_tool(
    agent: object,
    tool_name: str,
    args: Any,
    *,
    timeout_seconds: float | None,
    cancel_source: Any = None,
) -> tuple[bool, Any]:
    target = remote_workspace_target(agent, tool_name)
    if target is None:
        return False, None
    task_id = uuid.uuid4().hex
    payload = {
        "task_id": task_id,
        "worker_id": target.worker_id,
        "tool_name": str(tool_name),
        "arguments": args if isinstance(args, dict) else {},
        "working_path": target.working_path,
        "timeout_seconds": _request_timeout_seconds(tool_name, args, timeout_seconds),
    }
    unregister_cancel = register_cancel_callback(
        cancel_source,
        lambda: _post_internal_request(
            f"/api/remote-workers/internal/tasks/{task_id}/cancel",
            {"worker_id": target.worker_id},
            10.0,
        ),
    )
    try:
        raise_if_cancel_requested(cancel_source)
        response = _post_internal_request(
            "/api/remote-workers/internal/execute",
            payload,
            payload["timeout_seconds"] + (50.0 if target.worker_id.startswith("peer:") else 10.0),
        )
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error") or "Remote workspace execution failed."))
        return True, response.get("result")
    finally:
        unregister_cancel()


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


def _post_internal_request(path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    port = str(os.environ.get("AGENTPARK_SERVER_PORT") or "8766").strip() or "8766"
    url = f"http://127.0.0.1:{port}{path}"
    request = dict(url=url, body=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        response = CurlHttpTransport().request(**request, timeout_sec=max(2.0, float(timeout))).raise_for_status()
        body = response.content.decode("utf-8", errors="replace")
    except CurlHttpError as exc:
        detail = exc.content.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Remote workspace request failed with HTTP {exc.status_code}: {detail}") from exc
    except OSError as exc:
        raise RuntimeError(f"Remote workspace request failed: {type(exc).__name__}: {exc}") from exc
    try:
        decoded = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Remote workspace returned invalid JSON.") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("Remote workspace returned a non-object response.")
    return decoded
