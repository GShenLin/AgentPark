from src.harness.node import HarnessNode
from src.harness.config import CLI_DEFAULTS, CLI_SCHEMA


class Node(HarnessNode):
    harness_id = "pi"
    name = "Pi"
    description = "Run Pi with an AgentPark Provider and Model (developer access required)."
    config_defaults = CLI_DEFAULTS
    config_schema = CLI_SCHEMA
