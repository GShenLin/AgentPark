from src.harness.node import HarnessNode
from src.harness.config import CLI_DEFAULTS, CLI_SCHEMA, REASONING_SCHEMA


class Node(HarnessNode):
    harness_id = "opencode"
    name = "OpenCode CLI"
    description = "Run OpenCode tools with the selected AgentPark Provider and model."
    provider_reasoning_options = True
    config_defaults = {**CLI_DEFAULTS, "agent_mode": "build", "reasoning_effort": ""}
    config_schema = {**CLI_SCHEMA,
        "agent_mode": {"type": "string", "label": "OpenCode Agent", "description": "原生 Agent 名称，例如 build 或 plan。"},
        "reasoning_effort": REASONING_SCHEMA,
    }
