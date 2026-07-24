"""Static capability and configuration contract for the Codex node."""


CODEX_INPUT_CAPABILITIES = [
    "text",
    "resource:image",
    "resource:video",
    "resource:audio",
    "resource:doc",
    "resource:file",
    "resource:url",
    "structured",
    "meta",
]

CODEX_OUTPUT_CAPABILITIES = ["text", "structured", "tool_call", "meta"]

CODEX_CONFIG_DEFAULTS = {
    "provider_id": "",
    "instruction": "",
    "codex_command": "codex",
    "sandbox": "workspace-write",
    "reasoning_effort": "high",
    "web_search": "disabled",
}

CODEX_CONFIG_SCHEMA = {
    "provider_id": {
        "type": "select",
        "label": "provider_id",
        "options": [],
        "description": "Select a configured Provider that supports chat or imagechat.",
    },
    "instruction": {
        "type": "text",
        "label": "instruction",
        "description": "Persistent developer instructions passed to the real Codex thread.",
    },
    "codex_command": {
        "type": "text",
        "label": "Codex Command",
        "description": "Codex executable or codex.cmd path used to start app-server.",
    },
    "sandbox": {
        "type": "select",
        "label": "Sandbox",
        "options": [
            {"value": "read-only", "label": "read-only"},
            {"value": "workspace-write", "label": "workspace-write"},
            {"value": "danger-full-access", "label": "danger-full-access"},
        ],
    },
    "reasoning_effort": {
        "type": "select",
        "label": "reasoning_effort",
        "options": [
            {"value": value, "label": value}
            for value in ("minimal", "low", "medium", "high", "xhigh", "ultra")
        ],
    },
    "web_search": {
        "type": "select",
        "label": "web_search",
        "options": [
            {"value": value, "label": value}
            for value in ("disabled", "cached", "live")
        ],
        "description": "Hosted web search is available only through a Responses Provider.",
    },
}
