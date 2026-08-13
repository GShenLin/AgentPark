from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any


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


__all__ = ["PublicGatewayAccessLog", "safe_error_message"]
