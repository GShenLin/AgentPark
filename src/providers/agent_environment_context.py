from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from src.workspace_settings import get_workspace_root


ENVIRONMENT_CONTEXT_TEXT_PREFIX = "[Agent Environment Context]\n"


def build_agent_environment_context(agent: object, *, current_input: object | None = None) -> dict[str, str]:
    _ = current_input
    context: dict[str, str] = {}

    workspace_root = _normalized_path(_first_non_empty(getattr(agent, "_aitools_workspace_root", None), get_workspace_root()))
    if workspace_root:
        context["workspace_root"] = workspace_root

    working_path = _normalized_path(
        _first_non_empty(
            getattr(agent, "_aitools_working_path", None),
            _config_value(agent, "working_path"),
            workspace_root,
        )
    )
    if working_path:
        context["working_path"] = working_path

    shell = _resolve_shell(agent)
    if shell:
        context["shell"] = shell

    context["request_time"] = datetime.now().astimezone().isoformat(timespec="seconds")
    return context


def format_agent_environment_context(context: dict[str, Any]) -> str:
    import json

    safe_context = {
        str(key): str(value)
        for key, value in sorted((context or {}).items())
        if str(key or "").strip() and value is not None and str(value).strip()
    }
    return ENVIRONMENT_CONTEXT_TEXT_PREFIX + json.dumps(safe_context, ensure_ascii=False, sort_keys=True)


def is_agent_environment_context_text(value: object) -> bool:
    return isinstance(value, str) and value.startswith(ENVIRONMENT_CONTEXT_TEXT_PREFIX)


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


def _normalized_path(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return os.path.normpath(os.path.abspath(os.path.expanduser(text)))


def _resolve_shell(agent: object) -> str:
    value = _first_non_empty(getattr(agent, "_aitools_shell", None), _config_value(agent, "shell"))
    if value:
        return value
    if os.name == "nt":
        return "powershell"
    return os.path.basename(os.environ.get("SHELL") or "sh") or "sh"
