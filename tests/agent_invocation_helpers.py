"""Explicit invocation setup for orchestration tests that replace the factory.

Real adapter signatures and factory mapping are exercised separately in
test_agent_parameter_mapping.py, rather than inferred from permissive fakes.
"""
from src.providers.agent_config import AgentConfig
from src.providers.agent_invocation import AgentInvocation
from src.providers.parameter_mapping import PROVIDER_PARAMETER_MAPPINGS


def configured_fake(agent, agent_config=None):
    config = agent_config if agent_config is not None else AgentConfig()
    agent._agent_invocation = AgentInvocation(
        "test", "openai", PROVIDER_PARAMETER_MAPPINGS["openai"], config.values(), {},
    )
    return agent
