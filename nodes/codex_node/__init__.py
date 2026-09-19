from src.harness.node import HarnessNode
from .contract import CODEX_CONFIG_DEFAULTS, CODEX_CONFIG_SCHEMA


class Node(HarnessNode):
    harness_id = "codex"
    name = "Codex"
    description = "Run Codex with an AgentPark Provider and Model."
    config_defaults = CODEX_CONFIG_DEFAULTS
    config_schema = CODEX_CONFIG_SCHEMA
