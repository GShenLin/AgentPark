import json
import os

from nodes.base_node import BaseNode


class Node(BaseNode):
    name = "Event"
    description = "事件节点：按 EventKey 分发输入"
    config_defaults = {"EventKey": ""}
    config_schema = {"EventKey": {"type": "text", "label": "EventKey"}}

    def getInputNum(self, context: dict | None = None) -> int:
        return 1

    def getOutputNum(self, context: dict | None = None) -> int:
        return 1

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        graph_id = str(ctx.get("graph_id") or "default").strip() or "default"
        node_instance_id = str(ctx.get("node_instance_id") or "").strip()

        event_key = ""
        if ctx.get("EventKey") is not None:
            event_key = str(ctx.get("EventKey") or "").strip()

        if node_instance_id and not event_key:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            node_dir = os.path.join(base_dir, "memories", graph_id, node_instance_id)
            config_path = os.path.join(node_dir, "config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict) and data.get("EventKey") is not None:
                        event_key = str(data.get("EventKey") or "").strip()
                except Exception:
                    event_key = ""
        envelope = self._normalize_message(message, default_role="assistant")

        return {
            "display": self._message_text(envelope),
            "routes": [{"output_index": 0, "payload": envelope}],
            "event_key": event_key,
        }
