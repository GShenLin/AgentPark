from __future__ import annotations

from typing import Any

from src.providers.agent_runtime_context import get_agent_runtime_context


PERMISSIONS_CONTEXT_TEXT_PREFIX = "<permissions instructions>"
PERMISSIONS_CONTEXT_TEXT_SUFFIX = "</permissions instructions>"


def build_agent_permissions_context(agent: object = None, environment_context: dict[str, Any] | None = None) -> dict[str, str]:
    _ = environment_context
    runtime_context = get_agent_runtime_context(agent)
    return {
        "sandbox_mode": _first_non_empty(
            runtime_context.sandbox_mode,
            _config_value(agent, "sandbox_mode"),
            "danger-full-access",
        ),
        "network_access": _first_non_empty(
            runtime_context.network_access,
            _config_value(agent, "network_access"),
            "enabled",
        ),
        "approval_policy": _first_non_empty(
            runtime_context.approval_policy,
            _config_value(agent, "approval_policy"),
            "never",
        ),
    }


def format_agent_permissions_context(context: dict[str, Any] | None = None) -> str:
    payload = build_agent_permissions_context() if context is None else context
    sandbox_mode = str(payload.get("sandbox_mode") or "danger-full-access").strip() or "danger-full-access"
    network_access = str(payload.get("network_access") or "enabled").strip() or "enabled"
    approval_policy = str(payload.get("approval_policy") or "never").strip() or "never"
    body = (
        "Filesystem sandboxing defines which files can be read or written. "
        f"`sandbox_mode` is `{sandbox_mode}`: No filesystem sandboxing - all commands are permitted. "
        f"Network access is {network_access}.\n"
        f"Approval policy is currently {approval_policy}. Do not provide the `sandbox_permissions` "
        "for any reason, commands will be rejected."
    )
    return f"{PERMISSIONS_CONTEXT_TEXT_PREFIX}\n{body}\n{PERMISSIONS_CONTEXT_TEXT_SUFFIX}"


def is_agent_permissions_context_text(value: object) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return text.startswith(PERMISSIONS_CONTEXT_TEXT_PREFIX) and text.endswith(PERMISSIONS_CONTEXT_TEXT_SUFFIX)


def _config_value(agent: object, key: str) -> object:
    config = getattr(agent, "config", None)
    if isinstance(config, dict):
        return config.get(key)
    return None


def _first_non_empty(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
