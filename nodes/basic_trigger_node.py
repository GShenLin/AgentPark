from nodes.base_node import BaseNode
from src.message_protocol import normalize_envelope


def _has_input_content(envelope: dict) -> bool:
    for part in envelope.get("parts", []):
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            if str(part.get("text") or ""):
                return True
            continue
        return True
    return False


class Node(BaseNode):
    name = "BasicTrigger"
    description = "基础触发器：手动点击触发"
    input_capabilities = [
        "text",
        "resource:image",
        "resource:video",
        "resource:audio",
        "resource:doc",
        "resource:file",
        "resource:url",
        "structured",
        "tool_call",
        "meta",
    ]
    output_capabilities = list(input_capabilities)
    config_defaults = {"OutputText": ""}
    config_schema = {"OutputText": {"type": "text", "label": "输出文本"}}

    def getInputNum(self, context: dict | None = None) -> int:
        return 1

    def getOutputNum(self, context: dict | None = None) -> int:
        return 1

    def on_input(self, message: object, context: dict | None = None) -> dict:
        envelope = normalize_envelope(message, default_role="user")
        if _has_input_content(envelope):
            return {
                "display_message": envelope,
                "routes": [{"output_index": 0, "payload": envelope}],
            }

        ctx = context or {}
        output_text = str(ctx.get("OutputText") or "")
        return self._text_output(output_text)
