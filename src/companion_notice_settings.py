from __future__ import annotations

from typing import Any

from src.config_loader import ConfigLoader
from src.value_parsing import parse_optional_bool_value


def companion_error_notice_enabled(config: dict[str, Any] | None = None) -> bool:
    payload = ConfigLoader().get_config() if config is None else config
    if not isinstance(payload, dict):
        raise ValueError("config must be a top-level object.")
    agent_node = payload.get("agentNode")
    if agent_node is None:
        return True
    if not isinstance(agent_node, dict):
        raise ValueError("config.json field 'agentNode' must be an object.")
    parsed = parse_optional_bool_value(
        "agentNode.notifyCompanionOnError",
        agent_node.get("notifyCompanionOnError"),
    )
    return True if parsed is None else parsed


__all__ = ["companion_error_notice_enabled"]
