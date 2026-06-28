import pytest

from nodes.agent_node_settings import AgentNodeSettingsError
from nodes.agent_node_settings import resolve_agent_node_settings


def test_resolve_agent_node_settings_accepts_config_json_values():
    settings = resolve_agent_node_settings(
        {
            "agentNode": {
                "minSendDelayMs": "200",
                "historyMessageLimit": "40",
            }
        }
    )

    assert settings.min_send_delay_ms == 200
    assert settings.history_message_limit == 40


def test_resolve_agent_node_settings_rejects_invalid_history_limit():
    with pytest.raises(AgentNodeSettingsError, match="historyMessageLimit"):
        resolve_agent_node_settings({"agentNode": {"historyMessageLimit": 0}})


def test_resolve_agent_node_settings_rejects_boolean_numbers():
    with pytest.raises(AgentNodeSettingsError, match="minSendDelayMs"):
        resolve_agent_node_settings({"agentNode": {"minSendDelayMs": True}})
