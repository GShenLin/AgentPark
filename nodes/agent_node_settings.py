from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.value_parsing import parse_optional_int_value


@dataclass(frozen=True)
class AgentNodeSettings:
    min_send_delay_ms: int = 0
    history_message_limit: int = 40


class AgentNodeSettingsError(ValueError):
    pass


def resolve_agent_node_settings(config: dict[str, Any]) -> AgentNodeSettings:
    node_config = _agent_node_config(config)
    return AgentNodeSettings(
        min_send_delay_ms=_optional_positive_int(
            node_config,
            keys=("minSendDelayMs", "min_send_delay_ms"),
            default=0,
            field_name="agentNode.minSendDelayMs",
            allow_zero=True,
        ),
        history_message_limit=_optional_positive_int(
            node_config,
            keys=("historyMessageLimit", "history_message_limit"),
            default=40,
            field_name="agentNode.historyMessageLimit",
            allow_zero=False,
        ),
    )


def _agent_node_config(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        return {}
    node_config = config.get("agentNode")
    if node_config is None:
        node_config = config.get("agent_node")
    if node_config is None:
        return {}
    if not isinstance(node_config, dict):
        raise AgentNodeSettingsError("agentNode must be an object.")
    return node_config


def _optional_positive_int(
    config: dict[str, Any],
    *,
    keys: tuple[str, ...],
    default: int,
    field_name: str,
    allow_zero: bool,
) -> int:
    raw = None
    for key in keys:
        if key in config:
            raw = config.get(key)
            break
    if raw is None or raw == "":
        return default
    try:
        value = parse_optional_int_value(field_name, raw)
    except ValueError as exc:
        raise AgentNodeSettingsError(f"{field_name} must be an integer: {raw!r}") from exc
    if value is None:
        return default
    if value < 0 or (value == 0 and not allow_zero):
        raise AgentNodeSettingsError(f"{field_name} must be greater than zero.")
    return value
