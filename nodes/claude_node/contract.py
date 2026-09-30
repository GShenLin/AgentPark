"""Public capability and configuration contract for the Claude Code node."""


CLAUDE_INPUT_CAPABILITIES = [
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

CLAUDE_OUTPUT_CAPABILITIES = ["text", "structured", "tool_call", "meta"]

CLAUDE_CONFIG_DEFAULTS = {
    "provider_id": "",
    "model": "",
    "instruction": "",
    "claude_command": "claude",
    "permission_mode": "acceptEdits",
    "reasoning_effort": "high",
}

CLAUDE_CONFIG_SCHEMA = {
    "provider_id": {
        "type": "select",
        "label": "provider_id",
        "options": [],
        "description": "Select a configured Provider that supports chat.",
    },
    "instruction": {
        "type": "text",
        "label": "instruction",
        "description": "Persistent instructions appended to Claude Code's system prompt.",
    },
    "claude_command": {
        "type": "text",
        "label": "Claude Command",
        "description": "Claude executable or command. On Windows this resolves to the native claude.exe.",
    },
    "permission_mode": {
        "type": "select",
        "label": "Permission Mode",
        "options": [
            {"value": value, "label": value}
            for value in ("plan", "dontAsk", "acceptEdits", "auto", "bypassPermissions")
        ],
        "description": "Native Claude Code permission policy. This is not a filesystem sandbox.",
    },
    "reasoning_effort": {
        "type": "select",
        "label": "reasoning_effort",
        "options": [
            {"value": value, "label": value}
            for value in ("low", "medium", "high", "xhigh", "max")
        ],
    },
}
