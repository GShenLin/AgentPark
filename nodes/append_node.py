from nodes.base_node import BaseNode
from src.message_protocol import envelope_text


class Node(BaseNode):
    name = "Append"
    description = "在输入末尾追加固定文本"
    config_defaults = {"AppendText": ""}
    config_schema = {"AppendText": {"type": "text", "label": "追加文本"}}

    def getInputNum(self, context: dict | None = None) -> int:
        return 1

    def getOutputNum(self, context: dict | None = None) -> int:
        return 1

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        append_text = str(ctx.get("AppendText") or "")
        input_text = envelope_text(message)
        output_text = f"{input_text}{append_text}"
        return self._text_output(output_text)
