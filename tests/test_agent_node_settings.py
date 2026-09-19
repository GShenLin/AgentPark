import pytest

from nodes.agent_node_settings import AgentNodeSettingsError
from nodes.agent_node_settings import resolve_agent_node_settings


def test_resolve_agent_node_settings_defaults():
    settings = resolve_agent_node_settings({})

    assert settings.min_send_delay_ms == 0


def test_resolve_agent_node_settings_accepts_config_json_values():
    settings = resolve_agent_node_settings(
        {
            "agentNode": {
                "minSendDelayMs": "200",
            }
        }
    )

    assert settings.min_send_delay_ms == 200


def test_resolve_agent_node_settings_rejects_negative_delay():
    with pytest.raises(AgentNodeSettingsError, match="minSendDelayMs"):
        resolve_agent_node_settings({"agentNode": {"minSendDelayMs": -1}})


def test_resolve_agent_node_settings_rejects_boolean_numbers():
    with pytest.raises(AgentNodeSettingsError, match="minSendDelayMs"):
        resolve_agent_node_settings({"agentNode": {"minSendDelayMs": True}})
