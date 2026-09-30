from src.harness.node import HarnessNode
from src.harness.config import CLI_DEFAULTS, CLI_SCHEMA, REASONING_SCHEMA


class Node(HarnessNode):
    harness_id = "minimax_code"
    provider_reasoning_options = True
    name = "MiniMax Code"
    description = "Run MiniMax Code with an AgentPark Provider and Model (developer access required)."
    config_defaults = {**CLI_DEFAULTS, "reasoning_effort": "", "permission_mode": "auto"}
    config_schema = {**CLI_SCHEMA, "reasoning_effort": REASONING_SCHEMA,
                     "permission_mode": {"type": "select", "label": "工具执行权限",
                         "options": ["default", "auto", "bypassPermissions"],
                         "description": "auto 自动处理常规操作；bypassPermissions 完全访问，仅用于已信任的任务和工作目录。"}}
