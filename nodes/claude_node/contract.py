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
    "permission_mode": "bypassPermissions",
    "reasoning_effort": "high",
    "inherit_mcp_servers": False,
}

CLAUDE_CONFIG_SCHEMA = {
    "inherit_mcp_servers": {
        "type": "boolean", "label": "加载外部 MCP 服务",
        "description": "加载 Claude 用户和项目配置中的 MCP 服务。关闭时仍可使用原生文件、命令等工具；开启可能增加启动耗时。",
    },
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
            {"value": value, "label": label}
            for value, label in (
                ("bypassPermissions", "Full Access (bypassPermissions)"),
                ("acceptEdits", "acceptEdits"),
                ("default", "default"),
                ("auto", "auto"),
                ("dontAsk", "dontAsk"),
                ("plan", "plan (read-only)"),
            )
        ],
        "description": "Native Claude Code permission policy. Node turns run unattended, so tool prompts are resolved automatically instead of blocking. This is not a filesystem sandbox.",
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
