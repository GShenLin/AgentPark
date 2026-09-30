from __future__ import annotations

from typing import TypedDict

from . import workspace_settings


class AgentPanelSettings(TypedDict):
    width: int
    height: int


def normalize_agent_panel_settings(value: object) -> AgentPanelSettings:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("config.json field 'agentPanel' must be an object")

    def dimension(key: str, default: int, minimum: int) -> int:
        number = value.get(key, default)
        if type(number) is not int or not minimum <= number <= 7680:
            raise ValueError(
                f"config.json field 'agentPanel.{key}' must be an integer between {minimum} and 7680"
            )
        return number

    return {
        "width": dimension("width", 1040, 360),
        "height": dimension("height", 820, 320),
    }


def read_agent_panel_settings() -> AgentPanelSettings:
    return normalize_agent_panel_settings(workspace_settings.load_workspace_settings().get("agentPanel"))
