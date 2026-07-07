from __future__ import annotations

from typing import Any

from src.config_loader import ConfigLoader
from src.value_parsing import parse_optional_bool_value


def companion_node_review_enabled(config: dict[str, Any] | None = None) -> bool:
    payload = ConfigLoader().get_config() if config is None else config
    parsed = _parse_agent_node_bool_setting(payload, "reviewNodeRunsWithCompanion")
    return False if parsed is None else parsed


def companion_tool_failure_memory_enabled(config: dict[str, Any] | None = None) -> bool:
    payload = ConfigLoader().get_config() if config is None else config
    parsed = _parse_agent_node_bool_setting(payload, "reviseToolFailureMemoryWithCompanion")
    return False if parsed is None else parsed


def _parse_agent_node_bool_setting(payload: object, key: str) -> bool | None:
    if not isinstance(payload, dict):
        raise ValueError("config must be a top-level object.")
    agent_node = payload.get("agentNode")
    if agent_node is None:
        return None
    if not isinstance(agent_node, dict):
        raise ValueError("config.json field 'agentNode' must be an object.")
    return parse_optional_bool_value(
        f"agentNode.{key}",
        agent_node.get(key),
    )


__all__ = ["companion_node_review_enabled", "companion_tool_failure_memory_enabled"]
