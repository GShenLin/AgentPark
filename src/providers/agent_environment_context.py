from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime
from functools import lru_cache
from importlib import import_module
from typing import Any

from src.providers.agent_runtime_context import get_agent_runtime_context
from src.workspace_settings import get_workspace_root


ENVIRONMENT_CONTEXT_TEXT_PREFIX = "<environment_context>"
ENVIRONMENT_CONTEXT_TEXT_SUFFIX = "</environment_context>"
MODEL_VISIBLE_ENVIRONMENT_CONTEXT_KEYS = {"current_date", "shell", "timezone", "workspace_path"}
WINDOWS_TIMEZONE_TO_IANA = {
    "China Standard Time": "Asia/Shanghai",
    "Taipei Standard Time": "Asia/Taipei",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Korea Standard Time": "Asia/Seoul",
    "Singapore Standard Time": "Asia/Singapore",
    "UTC": "UTC",
    "Eastern Standard Time": "America/New_York",
    "Central Standard Time": "America/Chicago",
    "Mountain Standard Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles",
}


def build_agent_environment_context(agent: object, *, current_input: object | None = None) -> dict[str, str]:
    _ = current_input
    context: dict[str, str] = {}

    workspace_path = resolve_agent_model_workspace_path(agent)
    if workspace_path:
        context["workspace_path"] = workspace_path

    shell = _resolve_shell(agent)
    if shell:
        context["shell"] = shell

    now = datetime.now().astimezone()
    context["current_date"] = now.date().isoformat()
    timezone = _resolve_timezone(now)
    if timezone:
        context["timezone"] = timezone
    context["request_time"] = now.isoformat(timespec="seconds")
    return context


def resolve_agent_configured_working_path(agent: object) -> str:
    """Return the effective node/graph configured working path, or empty when unset."""
    configured = _first_non_empty(*resolve_agent_working_path_settings(agent))
    if configured and get_agent_runtime_context(agent).remote_enabled:
        return configured
    return _normalized_path(configured)


def resolve_agent_model_workspace_path(agent: object) -> str:
    """Return the model-visible workspace path, aligned with tool relative-path resolution."""
    root = resolve_agent_configured_working_path(agent)
    if root:
        if get_agent_runtime_context(agent).remote_enabled:
            return root
        if not os.path.isdir(root):
            raise ValueError(f"WorkingPath directory does not exist: {root}")
        return root
    runtime_context = get_agent_runtime_context(agent)
    return _resolve_local_default_directory(runtime_context)


def resolve_agent_working_path_settings(agent: object) -> tuple[str, str]:
    """Return raw node and graph working path settings in priority order."""
    runtime_context = get_agent_runtime_context(agent)
    node_path = _first_non_empty(
        runtime_context.working_path,
        _config_value(agent, "working_path"),
    )
    graph_path = _first_non_empty(
        runtime_context.graph_working_path,
        _config_value(agent, "graph_working_path"),
        _read_graph_working_path(runtime_context.graph_id),
    )
    return node_path, graph_path


def resolve_agent_relative_path(path: object, agent: object = None) -> str:
    """Resolve a tool path relative to the node-configured working path when present."""
    text = str(path or "").strip()
    if os.path.isabs(text):
        return os.path.normpath(os.path.abspath(os.path.expanduser(text)))
    root = resolve_agent_working_directory(agent)
    return os.path.normpath(os.path.abspath(os.path.join(root, os.path.expanduser(text))))


def resolve_agent_working_directory(agent: object = None) -> str:
    root = resolve_agent_configured_working_path(agent)
    if root and get_agent_runtime_context(agent).remote_enabled:
        return root
    if root and not os.path.isdir(root):
        raise ValueError(f"WorkingPath directory does not exist: {root}")
    if root:
        return root
    return _resolve_local_default_directory(get_agent_runtime_context(agent))


def _resolve_local_default_directory(runtime_context: object) -> str:
    """Resolve the local fallback after node and graph WorkingPath settings are absent."""
    root = _normalized_path(
        _first_non_empty(
            getattr(runtime_context, "node_directory", ""),
            getattr(runtime_context, "workspace_root", ""),
            get_workspace_root(),
            os.getcwd(),
        )
    )
    if not os.path.isdir(root):
        raise ValueError(f"Agent default working directory does not exist: {root}")
    return root


def format_agent_environment_context(context: dict[str, Any]) -> str:
    safe_context = {
        str(key): str(value)
        for key, value in sorted((context or {}).items())
        if str(key or "").strip() in MODEL_VISIBLE_ENVIRONMENT_CONTEXT_KEYS
        and value is not None
        and str(value).strip()
    }
    workspace_path = safe_context.get("workspace_path", "")
    lines = [ENVIRONMENT_CONTEXT_TEXT_PREFIX]
    if workspace_path:
        lines.append(f"  <cwd>{_xml_escape(workspace_path)}</cwd>")
    if safe_context.get("shell"):
        lines.append(f"  <shell>{_xml_escape(safe_context['shell'])}</shell>")
    if safe_context.get("current_date"):
        lines.append(f"  <current_date>{_xml_escape(safe_context['current_date'])}</current_date>")
    if safe_context.get("timezone"):
        lines.append(f"  <timezone>{_xml_escape(safe_context['timezone'])}</timezone>")
    if workspace_path:
        lines.append(
            "  <filesystem>"
            "<workspace_roots>"
            f"<root>{_xml_escape(workspace_path)}</root>"
            "</workspace_roots>"
            '<permission_profile type="disabled"><file_system type="unrestricted" /></permission_profile>'
            "</filesystem>"
        )
    lines.append(ENVIRONMENT_CONTEXT_TEXT_SUFFIX)
    return "\n".join(lines)


def is_agent_environment_context_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return text.startswith(ENVIRONMENT_CONTEXT_TEXT_PREFIX) and text.endswith(ENVIRONMENT_CONTEXT_TEXT_SUFFIX)


def _first_non_empty(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _config_value(agent: object, key: str) -> object:
    config = getattr(agent, "config", None)
    if isinstance(config, dict):
        return config.get(key)
    return None


def _read_graph_working_path(graph_id: object) -> str:
    graph_text = str(graph_id or "").strip()
    if not graph_text:
        return ""
    runtime_paths = import_module("src.web_backend.runtime_paths")
    config_path = os.path.join(runtime_paths._get_graphs_dir(), graph_text, "config.json")
    try:
        import json

        with open(config_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("working_path") or "").strip()


def _normalized_path(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return os.path.normpath(os.path.abspath(os.path.expanduser(text)))


def _resolve_shell(agent: object) -> str:
    runtime_context = get_agent_runtime_context(agent)
    value = _first_non_empty(runtime_context.shell, _config_value(agent, "shell"))
    if value:
        return value
    if os.name == "nt":
        return "powershell"
    return os.path.basename(os.environ.get("SHELL") or "sh") or "sh"


def _resolve_timezone(now: datetime) -> str:
    env_tz = str(os.environ.get("TZ") or "").strip()
    if env_tz:
        return env_tz
    windows_tz = _windows_timezone_name()
    if windows_tz:
        mapped = WINDOWS_TIMEZONE_TO_IANA.get(windows_tz)
        if mapped:
            return mapped
        return windows_tz
    name = str(now.tzname() or "").strip()
    if name:
        mapped = WINDOWS_TIMEZONE_TO_IANA.get(name)
        if mapped:
            return mapped
        return name
    offset = now.strftime("%z")
    if len(offset) == 5:
        return f"UTC{offset[:3]}:{offset[3:]}"
    return ""


@lru_cache(maxsize=1)
def _windows_timezone_name() -> str:
    if os.name != "nt":
        return ""
    try:
        output = subprocess.check_output(
            ["tzutil", "/g"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except Exception:
        return ""
    return str(output or "").strip()


def _xml_escape(value: object) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
