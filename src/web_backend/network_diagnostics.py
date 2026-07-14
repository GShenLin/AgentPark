from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .runtime_paths import _get_runtime_root

_MAX_LOG_BYTES = 5 * 1024 * 1024
_LOG_BACKUP_COUNT = 2


class NetworkDiagnosticsMiddleware:
    """Persist a small request trace for intermittent mobile network failures."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._write_lock = threading.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        started_at = datetime.now(timezone.utc)
        status_code: int | None = None

        async def capture_response(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, capture_response)
        except Exception as exc:
            self._append_record(scope, started_at, status_code, error=repr(exc))
            raise
        else:
            self._append_record(scope, started_at, status_code)

    def _append_record(
        self,
        scope: Scope,
        started_at: datetime,
        status_code: int | None,
        *,
        error: str = "",
    ) -> None:
        finished_at = datetime.now(timezone.utc)
        headers = Headers(scope=scope)
        client = scope.get("client")
        server = scope.get("server")
        record: dict[str, Any] = {
            "timestamp": finished_at.isoformat(),
            "duration_ms": round((finished_at - started_at).total_seconds() * 1000, 2),
            "method": str(scope.get("method") or ""),
            "path": str(scope.get("path") or ""),
            "query": bytes(scope.get("query_string") or b"").decode("utf-8", errors="replace"),
            "status": status_code,
            "client": _address_label(client),
            "server": _address_label(server),
            "origin": headers.get("origin", ""),
            "referer": headers.get("referer", ""),
            "user_agent": headers.get("user-agent", ""),
            "private_network_preflight": headers.get("access-control-request-private-network", ""),
        }
        if error:
            record["error"] = error

        log_dir = os.path.join(_get_runtime_root(), "logs")
        log_path = os.path.join(log_dir, "network-requests.jsonl")
        try:
            os.makedirs(log_dir, exist_ok=True)
            line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            with self._write_lock:
                _rotate_log_if_needed(log_path, len((line + "\n").encode("utf-8")))
                with open(log_path, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        except OSError as exc:
            print(f"[NetworkDiagnostics] failed to write {log_path}: {exc}")


def _address_label(value: object) -> str:
    if not isinstance(value, (tuple, list)) or not value:
        return ""
    host = str(value[0] or "")
    if len(value) < 2 or value[1] is None:
        return host
    return f"{host}:{value[1]}"


def _rotate_log_if_needed(log_path: str, incoming_bytes: int) -> None:
    try:
        current_bytes = os.path.getsize(log_path)
    except FileNotFoundError:
        return
    if current_bytes + incoming_bytes <= _MAX_LOG_BYTES:
        return
    for index in range(_LOG_BACKUP_COUNT, 0, -1):
        source = log_path if index == 1 else f"{log_path}.{index - 1}"
        target = f"{log_path}.{index}"
        if not os.path.exists(source):
            continue
        os.replace(source, target)


__all__ = ["NetworkDiagnosticsMiddleware"]
