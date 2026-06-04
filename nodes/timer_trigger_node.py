from datetime import datetime

from nodes.base_node import BaseNode


class Node(BaseNode):
    name = "TimerTrigger"
    description = "定时触发器：到达触发时间后输出文本"
    config_defaults = {
        "ScheduleAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "OutputText": "",
    }
    config_schema = {
        "ScheduleAt": {"type": "text", "label": "触发时间(YYYY-MM-DD HH:MM)"},
        "OutputText": {"type": "text", "label": "输出文本"},
    }

    def getInputNum(self, context: dict | None = None) -> int:
        return 1

    def getOutputNum(self, context: dict | None = None) -> int:
        return 1

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        output_text = str(ctx.get("OutputText") or "")
        return self._text_output(output_text)
