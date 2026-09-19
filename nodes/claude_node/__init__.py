from src.harness.node import HarnessNode
from .contract import CLAUDE_CONFIG_DEFAULTS, CLAUDE_CONFIG_SCHEMA


class Node(HarnessNode):
    harness_id = "claude"
    name = "Claude"
    description = "Run Claude with an AgentPark Provider and Model."
    config_defaults = CLAUDE_CONFIG_DEFAULTS
    config_schema = CLAUDE_CONFIG_SCHEMA
