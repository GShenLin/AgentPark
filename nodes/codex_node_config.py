from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from src.web_backend.node_config_service import read_node_config_optional
from src.workspace_settings import get_workspace_root


@dataclass(frozen=True)
class CodexNodeRunRequest:
    graph_id: str
    node_id: str
    provider_id: str
    instruction: str
    command: str
    cwd: str
    sandbox: str
    reasoning_effort: str
    web_search: str


def load_codex_node_run_request(context: dict[str, Any] | None, *, config_path: str) -> CodexNodeRunRequest:
    ctx = dict(context or {})
    config = _read_config(config_path)

    def setting(name: str, default: object = None) -> object:
        return config.get(name, default) if config is not None and name in config else ctx.get(name, default)

    provider_id = str(setting("provider_id") or "").strip()
    if not provider_id:
        raise ValueError("provider_id is required")
    command = str(setting("codex_command", "codex") or "").strip()
    if not command:
        raise ValueError("codex_command is required")
    sandbox = str(setting("sandbox", "workspace-write") or "").strip()
    if sandbox not in {"read-only", "workspace-write", "danger-full-access"}:
        raise ValueError(f"Unsupported Codex sandbox: {sandbox or '<empty>'}")
    reasoning_effort = str(setting("reasoning_effort", "high") or "").strip()
    if reasoning_effort not in {"minimal", "low", "medium", "high", "xhigh", "ultra"}:
        raise ValueError(f"Unsupported Codex reasoning_effort: {reasoning_effort or '<empty>'}")
    web_search = str(setting("web_search", "disabled") or "").strip()
    if web_search not in {"disabled", "cached", "live"}:
        raise ValueError(f"Unsupported Codex web_search mode: {web_search or '<empty>'}")

    workspace_root = os.path.abspath(get_workspace_root())
    raw_cwd = str(setting("working_path") or "").strip()
    cwd = os.path.abspath(os.path.expanduser(raw_cwd)) if raw_cwd else workspace_root
    if not os.path.isdir(cwd):
        raise ValueError(f"Codex working_path does not exist: {cwd}")

    return CodexNodeRunRequest(
        graph_id=str(ctx.get("graph_id") or "default").strip() or "default",
        node_id=str(ctx.get("node_instance_id") or ctx.get("node_id") or "codex").strip() or "codex",
        provider_id=provider_id,
        instruction=str(setting("instruction") or "").strip(),
        command=command,
        cwd=cwd,
        sandbox=sandbox,
        reasoning_effort=reasoning_effort,
        web_search=web_search,
    )


def _read_config(path: str) -> dict[str, Any] | None:
    if not path or not os.path.isfile(path):
        return None
    value = read_node_config_optional(path)
    if not isinstance(value, dict):
        raise ValueError("Codex node config must be a JSON object.")
    return value


__all__ = ["CodexNodeRunRequest", "load_codex_node_run_request"]
