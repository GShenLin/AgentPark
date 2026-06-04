from nodes.base_node import BaseNode


class Node(BaseNode):
    name = "BasicTrigger"
    description = "基础触发器：手动点击触发"
    config_defaults = {"OutputText": ""}
    config_schema = {"OutputText": {"type": "text", "label": "输出文本"}}

    def getInputNum(self, context: dict | None = None) -> int:
        return 1

    def getOutputNum(self, context: dict | None = None) -> int:
        return 1

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        output_text = str(ctx.get("OutputText") or "")
        return self._text_output(output_text)
