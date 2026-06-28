from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class McpLifecycleStatus:
    name: str
    state: str
    transport: str = ""
    diagnostics: tuple[str, ...] = ()
    tool_count: int = 0
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "transport": self.transport,
            "diagnostics": list(self.diagnostics),
            "tool_count": self.tool_count,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }


_VALID_STATES = {"configured", "starting", "ready", "failed", "stopped"}
_LOCK = threading.Lock()
_STATUSES: dict[str, McpLifecycleStatus] = {}


def mark_mcp_configured(name: str, *, transport: str = "", metadata: dict[str, Any] | None = None) -> McpLifecycleStatus:
    return _set_status(name, "configured", transport=transport, metadata=metadata)


def mark_mcp_starting(name: str, *, transport: str = "", metadata: dict[str, Any] | None = None) -> McpLifecycleStatus:
    return _set_status(name, "starting", transport=transport, metadata=metadata)


def mark_mcp_ready(
    name: str,
    *,
    transport: str = "",
    tool_count: int = 0,
    metadata: dict[str, Any] | None = None,
) -> McpLifecycleStatus:
    return _set_status(name, "ready", transport=transport, tool_count=max(0, int(tool_count or 0)), metadata=metadata)


def mark_mcp_failed(
    name: str,
    error: object,
    *,
    transport: str = "",
    metadata: dict[str, Any] | None = None,
) -> McpLifecycleStatus:
    diagnostic = str(error or "").strip() or "unknown MCP failure"
    return _set_status(name, "failed", transport=transport, diagnostics=(diagnostic,), metadata=metadata)


def mark_mcp_stopped(name: str, *, transport: str = "", metadata: dict[str, Any] | None = None) -> McpLifecycleStatus:
    return _set_status(name, "stopped", transport=transport, metadata=metadata)


def get_mcp_lifecycle_snapshot(name: str | None = None) -> dict[str, Any] | None:
    with _LOCK:
        if name is not None:
            status = _STATUSES.get(str(name or "").strip())
            return status.to_payload() if status else None
        return {key: value.to_payload() for key, value in sorted(_STATUSES.items())}


def reset_mcp_lifecycle() -> None:
    with _LOCK:
        _STATUSES.clear()


def _set_status(
    name: str,
    state: str,
    *,
    transport: str = "",
    diagnostics: tuple[str, ...] = (),
    tool_count: int = 0,
    metadata: dict[str, Any] | None = None,
) -> McpLifecycleStatus:
    server_name = str(name or "").strip()
    if not server_name:
        raise ValueError("MCP server name is required")
    if state not in _VALID_STATES:
        raise ValueError(f"invalid MCP lifecycle state: {state}")
    status = McpLifecycleStatus(
        name=server_name,
        state=state,
        transport=str(transport or "").strip(),
        diagnostics=tuple(str(item) for item in diagnostics if str(item or "").strip()),
        tool_count=max(0, int(tool_count or 0)),
        updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
        metadata=dict(metadata or {}),
    )
    with _LOCK:
        _STATUSES[server_name] = status
    return status
