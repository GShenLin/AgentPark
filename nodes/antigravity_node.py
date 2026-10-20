from src.harness.node import HarnessNode
from src.harness.adapters.antigravity_config import DEFAULT_MODEL


class Node(HarnessNode):
    harness_id = "antigravity"
    uses_agentpark_provider = False
    name = "Antigravity CLI"
    description = "Use Google Antigravity's native models, login and tools through its official CLI."
    config_defaults = {"native_model": DEFAULT_MODEL, "native_mode": "", "native_effort": "",
                       "native_auto_approve": False, "instruction": "", "timeout_seconds": 900}
    config_schema = {
        "native_model": {"type": "select", "label": "Antigravity 模型", "options": [],
            "description": "从当前账号的实际模型目录中选择；可刷新获取最新可用模型。"},
        "native_mode": {"type": "select", "label": "Antigravity 执行模式", "options": [
            {"value": "", "label": "原生默认权限"}, {"value": "plan", "label": "规划（plan）"},
            {"value": "accept-edits", "label": "允许编辑（accept-edits）"}],
            "description": "允许编辑模式不自动批准终端命令。未开启自动批准时，后台执行遵守原生权限规则，需要交互授权的操作将显示失败。"},
        "native_effort": {"type": "select", "label": "Antigravity 推理强度", "options": [
            {"value": "", "label": "模型默认"}, *[{"value": value, "label": value} for value in ("low", "medium", "high", "xhigh", "max")]]},
        "native_auto_approve": {"type": "boolean", "label": "自动批准所有工具",
            "description": "仅对这个节点的执行生效。开启后自动批准命令、文件写入等全部工具操作，无需交互确认；关闭后遵守 Antigravity 原生权限规则。"},
        "instruction": {"type": "text", "label": "instruction"},
        "timeout_seconds": {"type": "number", "label": "Timeout (seconds)", "min": 1, "max": 86400},
    }
