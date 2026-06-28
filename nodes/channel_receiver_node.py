from nodes.base_node import BaseNode
from src.message_protocol import normalize_envelope


class Node(BaseNode):
    name = "ChannelReceiver"
    description = "Receive external channel messages and forward them to downstream nodes."
    input_capabilities = ["text", "structured", "resource:file", "resource:image"]
    output_capabilities = ["text", "structured", "resource:file", "resource:image"]
    config_defaults = {
        "Channel": "openclaw-weixin",
        "Name": "",
        "Active": False,
        "AutoStart": False,
        "PollTimeoutSeconds": 35,
    }
    config_schema = {
        "Channel": {
            "type": "select",
            "label": "Channel",
            "options": [{"value": "openclaw-weixin", "label": "OpenClaw Weixin"}],
        },
        "Name": {
            "type": "text",
            "label": "Name",
            "description": "Optional command name. Sending /Name activates this receiver for later non-command messages.",
        },
        "Active": {
            "type": "boolean",
            "label": "Active",
            "description": "Persisted receiver switch set by /Name messages.",
        },
        "AutoStart": {
            "type": "boolean",
            "label": "AutoStart",
            "description": "Start this receiver when the backend starts.",
        },
        "PollTimeoutSeconds": {
            "type": "number",
            "label": "PollTimeoutSeconds",
            "min": 1,
            "max": 60,
            "step": 1,
        },
    }

    def getInputNum(self, context: dict | None = None) -> int:
        return 1

    def getOutputNum(self, context: dict | None = None) -> int:
        return 1

    def on_input(self, message: object, context: dict | None = None) -> dict:
        envelope = normalize_envelope(message, default_role="user")
        return {
            "display_message": envelope,
            "routes": [{"output_index": 0, "payload": envelope}],
        }
