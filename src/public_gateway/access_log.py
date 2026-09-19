from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Any
from fastapi import Request


_WRITE_LOCK = threading.Lock()


class PublicGatewayAccessLog:
    """Append-only, redacted request diagnostics for the public model gateway."""

    def __init__(self, workspace_root: str) -> None:
        self.path = os.path.join(workspace_root, ".runtime", "public-gateway-access.log")

    def record(self, event: str, **fields: Any) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": str(event),
            **fields,
        }
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with _WRITE_LOCK:
            with open(self.path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
                handle.flush()


def safe_error_message(exc: Exception, *, limit: int = 500) -> str:
    text = str(exc).replace("\r", " ").replace("\n", " ").strip()
    return text[:limit]


def request_fields(request: Request, request_id: str) -> dict[str, Any]:
    return {
        "requestId": request_id,
        "clientIp": request.client.host if request.client else "",
        "method": request.method,
        "path": request.url.path,
        "userAgent": request.headers.get("user-agent", "")[:200],
        "authorizationPresent": bool(request.headers.get("authorization") or request.headers.get("x-api-key")),
    }


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"


__all__ = ["PublicGatewayAccessLog", "safe_error_message", "request_fields", "new_request_id"]
