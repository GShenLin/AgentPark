from nodes.base_node import BaseNode
import json
import os
from src.message_protocol import envelope_text


class Node(BaseNode):
    name = "Echo"
    description = "回显输入"
    config_defaults = {"MyText": ""}
    config_schema = {"MyText": {"type": "text", "label": "MyText"}}

    def getInputNum(self, context: dict | None = None) -> int:
        return 1

    def getOutputNum(self, context: dict | None = None) -> int:
        return 1

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        graph_id = str(ctx.get("graph_id") or "default").strip() or "default"
        node_instance_id = str(ctx.get("node_instance_id") or "").strip()
        my_text = ""
        if ctx.get("MyText") is not None:
            my_text = str(ctx.get("MyText") or "")
        if node_instance_id:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            node_dir = os.path.join(base_dir, "memories", graph_id, node_instance_id)
            config_path = os.path.join(node_dir, "config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        if data.get("MyText") is not None:
                            my_text = str(data.get("MyText") or "")
                except Exception:
                    my_text = ""
        input_text = envelope_text(message)
        output_text = f"{my_text}{input_text}" if my_text else f"{input_text}"
        return self._text_output(output_text)
