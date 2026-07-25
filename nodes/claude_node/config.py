from __future__ import annotations

"""Configuration parsing for the Claude node."""

import os
from dataclasses import dataclass
from typing import Any

from src.web_backend.node_config_service import read_node_config_optional
from src.workspace_settings import get_workspace_root


@dataclass(frozen=True)
class ClaudeNodeRunRequest:
    graph_id: str
    node_id: str
    provider_id: str
    instruction: str
    command: str
    cwd: str
    permission_mode: str
    reasoning_effort: str


def load_claude_node_run_request(
    context: dict[str, Any] | None,
    *,
    config_path: str,
) -> ClaudeNodeRunRequest:
    ctx = dict(context or {})
    config = _read_config(config_path)

    def setting(name: str, default: object = None) -> object:
        return config.get(name, default) if config is not None and name in config else ctx.get(name, default)

    provider_id = str(setting("provider_id") or "").strip()
    if not provider_id:
        raise ValueError("provider_id is required")
    command = str(setting("claude_command", "claude") or "").strip()
    if not command:
        raise ValueError("claude_command is required")
    permission_mode = str(setting("permission_mode", "acceptEdits") or "").strip()
    if permission_mode not in {"plan", "dontAsk", "acceptEdits", "auto", "bypassPermissions"}:
        raise ValueError(f"Unsupported Claude permission_mode: {permission_mode or '<empty>'}")
    reasoning_effort = str(setting("reasoning_effort", "high") or "").strip()
    if reasoning_effort not in {"low", "medium", "high", "xhigh", "max"}:
        raise ValueError(f"Unsupported Claude reasoning_effort: {reasoning_effort or '<empty>'}")

    workspace_root = os.path.abspath(get_workspace_root())
    raw_cwd = str(setting("working_path") or "").strip()
    cwd = os.path.abspath(os.path.expanduser(raw_cwd)) if raw_cwd else workspace_root
    if not os.path.isdir(cwd):
        raise ValueError(f"Claude working_path does not exist: {cwd}")

    return ClaudeNodeRunRequest(
        graph_id=str(ctx.get("graph_id") or "default").strip() or "default",
        node_id=str(ctx.get("node_instance_id") or ctx.get("node_id") or "claude").strip() or "claude",
        provider_id=provider_id,
        instruction=str(setting("instruction") or "").strip(),
        command=command,
        cwd=cwd,
        permission_mode=permission_mode,
        reasoning_effort=reasoning_effort,
    )


def _read_config(path: str) -> dict[str, Any] | None:
    if not path or not os.path.isfile(path):
        return None
    value = read_node_config_optional(path)
    if not isinstance(value, dict):
        raise ValueError("Claude node config must be a JSON object.")
    return value


__all__ = ["ClaudeNodeRunRequest", "load_claude_node_run_request"]
