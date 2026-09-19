from src.harness.node import HarnessNode
from src.harness.config import CLI_DEFAULTS, CLI_SCHEMA, REASONING_SCHEMA


class Node(HarnessNode):
    harness_id = "openclaw"
    provider_reasoning_options = True
    name = "OpenClaw"
    description = "Run OpenClaw with an AgentPark Provider and Model (developer access required)."
    config_defaults = {**CLI_DEFAULTS, "reasoning_effort": ""}
    config_schema = {**CLI_SCHEMA, "reasoning_effort": REASONING_SCHEMA}
