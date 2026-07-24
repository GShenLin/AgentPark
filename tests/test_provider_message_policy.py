import pytest

from src.providers.provider_message_policy import MESSAGE_KIND_FIELD
from src.providers.provider_message_policy import ProviderMessagePolicy
from src.providers.provider_message_policy import ProviderMessagePolicyMixin
from src.providers.provider_message_policy import RUNTIME_INSTRUCTION_KIND


def test_chat_policy_resolves_runtime_instruction_to_system():
    policy = ProviderMessagePolicy.from_config({"responsesApi": False})

    message = policy.runtime_instruction_message("Keep the tool warning visible.")
    normalized = policy.normalize_messages([message])

    assert message[MESSAGE_KIND_FIELD] == RUNTIME_INSTRUCTION_KIND
    assert normalized == [{"role": "system", "content": "Keep the tool warning visible."}]


def test_responses_policy_maps_runtime_and_explicit_system_messages_to_developer():
    policy = ProviderMessagePolicy.from_config({"responsesApi": True})

    normalized = policy.normalize_messages(
        [
            policy.runtime_instruction_message("Runtime warning."),
            {"role": "system", "content": "Node prompt."},
            {"role": "user", "content": "Continue."},
        ]
    )

    assert normalized == [
        {"role": "developer", "content": "Runtime warning."},
        {"role": "developer", "content": "Node prompt."},
        {"role": "user", "content": "Continue."},
    ]


def test_provider_message_policy_requires_boolean_responses_contract():
    with pytest.raises(ValueError, match="provider.responsesApi must be a boolean"):
        ProviderMessagePolicy.from_config({"responsesApi": "true"})


def test_runtime_instruction_is_resolved_again_after_provider_config_loads():
    class DummyAgent(ProviderMessagePolicyMixin):
        def __init__(self):
            self.config = {}
            self.messages = []
            self.internal_memory_enabled = False

    agent = DummyAgent()
    message = agent.RuntimeInstruction("Constructed before provider config loading.")
    assert message["role"] == "system"

    agent.config = {"responsesApi": True}

    assert agent._normalize_provider_messages(agent.messages) == [
        {
            "role": "developer",
            "content": "Constructed before provider config loading.",
        }
    ]


def test_runtime_instruction_rejects_policy_owned_field_overrides():
    policy = ProviderMessagePolicy.from_config({"responsesApi": True})

    with pytest.raises(ValueError, match="policy-owned"):
        policy.runtime_instruction_message("Do not override roles.", role="system")
