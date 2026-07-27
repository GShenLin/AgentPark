from nodes.base_node import BaseNode
from src.message_protocol import envelope_text
from src.value_parsing import parse_bool_value


class Node(BaseNode):
    name = "Append"
    description = "在输入前面或末尾追加固定文本"
    config_defaults = {
        "AppendText": "",
        "AppendAtFront": False,
        "AutoNewline": True,
    }
    config_schema = {
        "AppendText": {"type": "text", "label": "追加文本"},
        "AppendAtFront": {
            "type": "boolean",
            "label": "追加到前面",
            "description": "开启时追加到输入前面；关闭时追加到输入末尾。",
        },
        "AutoNewline": {
            "type": "boolean",
            "label": "自动换行",
            "description": "在追加文本与输入文本之间自动插入换行。",
        },
    }

    def getInputNum(self, context: dict | None = None) -> int:
        return 1

    def getOutputNum(self, context: dict | None = None) -> int:
        return 1

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        append_text = str(ctx.get("AppendText") or "")
        input_text = envelope_text(message)
        append_at_front = parse_bool_value(ctx.get("AppendAtFront"), default=False)
        auto_newline = parse_bool_value(ctx.get("AutoNewline"), default=True)

        first, second = (append_text, input_text) if append_at_front else (input_text, append_text)
        separator = "\n" if auto_newline and first and second else ""
        output_text = f"{first}{separator}{second}"
        return self._text_output(output_text)
