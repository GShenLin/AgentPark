from src.harness.node import HarnessNode
from src.harness.adapters.antigravity_config import DEFAULT_MODEL


class Node(HarnessNode):
    harness_id = "antigravity"
    uses_agentpark_provider = False
    name = "Antigravity CLI"
    description = "Use Google Antigravity's native models, login and tools through its official CLI."
    config_defaults = {"native_model": DEFAULT_MODEL, "native_mode": "", "native_effort": "",
                       "instruction": "", "timeout_seconds": 900}
    config_schema = {
        "native_model": {"type": "text", "label": "Antigravity 模型", "placeholder": DEFAULT_MODEL,
            "description": "填写设置 → Harness 中当前账号的完整模型标识。Gemini 4 仅在账号模型目录包含时可用。"},
        "native_mode": {"type": "select", "label": "Antigravity 执行模式", "options": [
            {"value": "", "label": "原生默认权限"}, {"value": "plan", "label": "规划（plan）"},
            {"value": "accept-edits", "label": "允许编辑（accept-edits）"}],
            "description": "后台运行不能弹出 CLI 授权窗口；需授权的操作将显示失败。允许编辑模式由原生 CLI 控制，终端命令仍遵守其权限规则。"},
        "native_effort": {"type": "select", "label": "Antigravity 推理强度", "options": [
            {"value": "", "label": "模型默认"}, *[{"value": value, "label": value} for value in ("low", "medium", "high", "xhigh", "max")]]},
        "instruction": {"type": "text", "label": "instruction"},
        "timeout_seconds": {"type": "number", "label": "Timeout (seconds)", "min": 1, "max": 86400},
    }
