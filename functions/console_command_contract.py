"""Public console tool schema, independent of the execution platform."""

MIN_PROGRESS_TIMEOUT_SECONDS = 5
MAX_PROGRESS_TIMEOUT_SECONDS = 300


execute_console_command_declaration = {
    "type": "function",
    "function": {
        "name": "execute_console_command",
        "description": (
            "Execute a shell command on the local machine. Prefer structured tools "
            "(rg_search_text/rg_list_files) for file and text search. Use the shell reported in "
            "environment_context. Windows runs PowerShell with -NoProfile -Command; "
            "Termux, Linux and macOS run the detected POSIX shell with -c. "
            "On POSIX use pwd, ls, pipelines and POSIX quoting; commands are not translated between shells. "
            "On Windows use PowerShell syntax such as Get-ChildItem, "
            "Get-Location, pipelines, semicolon-separated statements, and & before quoted executable paths. "
            "Native non-zero exit codes are propagated. If a native outcome such as rg exit 1 for no matches "
            "is an expected branch, inspect $LASTEXITCODE explicitly and end the script with exit 0 only after "
            "validating that outcome; do not rely on PowerShell to mask it. "
            "Large stdout/stderr values are hard-limited; successful commands retain tail content, while "
            "failed or timed-out commands retain both the beginning and tail with explicit truncation metadata."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Command in the detected shell syntax (PowerShell on Windows; POSIX shell on Termux/Linux/macOS).",
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": (
                        "Optional command timeout in seconds. Defaults to 120; use 300 or more for known long "
                        "project builds such as WebUI production builds. Use 0 to disable the command timeout "
                        "and rely on Stop cancellation."
                    ),
                },
                "progress_timeout_seconds": {
                    "type": ["number", "null"],
                    "description": (
                        "Optional pytest-only semantic no-progress watchdog. It terminates the "
                        "test command when no quiet progress glyph run or verbose test terminal "
                        "status appears on stdout for this many seconds. Repeated logs and "
                        "tracebacks do not count as progress. Use null to disable it. A numeric "
                        f"value must be between {MIN_PROGRESS_TIMEOUT_SECONDS} and "
                        f"{MAX_PROGRESS_TIMEOUT_SECONDS} and less than timeout_seconds."
                    ),
                }
            },
            "required": ["command"],
        },
    },
}
