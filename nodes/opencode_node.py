from src.harness.node import HarnessNode
from src.harness.adapters.opencode_config import DEFAULT_MODEL


class Node(HarnessNode):
    harness_id = "opencode"
    uses_agentpark_provider = False
    name = "OpenCode CLI"
    description = "Use OpenCode's own models, credentials and tools through its official CLI."
    config_defaults = {"native_model": DEFAULT_MODEL, "native_agent": "build", "native_effort": "",
                       "instruction": "", "timeout_seconds": 900}
    config_schema = {
        "native_model": {"type": "select", "label": "OpenCode 模型", "options": [],
            "description": "从 OpenCode 当前可用模型中选择。免费额度和可用时间由 OpenCode 决定。"},
        "native_agent": {"type": "select", "label": "OpenCode Agent", "options": [], "description": "从当前工作目录可用的原生 Agent 中选择。"},
        "native_effort": {"type": "select", "label": "OpenCode 推理强度", "options": [], "description": "选项随模型更新；未提供额外选项时使用模型默认值。"},
        "instruction": {"type": "text", "label": "instruction"},
        "timeout_seconds": {"type": "number", "label": "Timeout (seconds)", "min": 1, "max": 86400},
    }
