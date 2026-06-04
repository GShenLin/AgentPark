from nodes.base_node import BaseNode
import json
import os


class Node(BaseNode):
    name = "Response"
    description = "返回 MyText"
    config_defaults = {"MyText": ""}
    config_schema = {"MyText": {"type": "text", "label": "MyText"}}

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        graph_id = str(ctx.get("graph_id") or "default").strip() or "default"
        node_instance_id = str(ctx.get("node_instance_id") or "").strip()
        my_text = ""
        if ctx.get("MyText") is not None:
            my_text = str(ctx.get("MyText") or "")
        if node_instance_id and not my_text:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            node_dir = os.path.join(base_dir, "memories", graph_id, node_instance_id)
            config_path = os.path.join(node_dir, "config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict) and data.get("MyText") is not None:
                        my_text = str(data.get("MyText") or "")
                except Exception:
                    my_text = ""
        output_text = f"{my_text}" if my_text else self._message_text(message)
        return self._text_output(output_text)
