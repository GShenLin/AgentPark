import json
import locale
import subprocess


def _preferred_text_encodings(command: str) -> list[str]:
    encodings: list[str] = []
    command_text = str(command or "").lower()
    if "powershell" in command_text or "pwsh" in command_text:
        encodings.extend(["utf-8", "utf-8-sig"])

    locale_encoding = locale.getpreferredencoding(False) or locale.getpreferredencoding() or "utf-8"
    encodings.append(locale_encoding)
    encodings.extend(["utf-8", "utf-8-sig"])

    deduped: list[str] = []
    seen: set[str] = set()
    for item in encodings:
        key = str(item or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _decode_output(data: bytes | None, command: str) -> str:
    if not data:
        return ""
    for encoding in _preferred_text_encodings(command):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode(_preferred_text_encodings(command)[0], errors="replace")


def execute_console_command(command):
    """
    Executes a console command and returns the output.
    Has a 15-second timeout. If it times out, returns captured output so far (if possible) or a timeout message.
    """
    try:
        cmd_lower = str(command).lower()
        if "findstr" in cmd_lower and "/s" in cmd_lower and ("*.h" in cmd_lower or "*.cpp" in cmd_lower or "*.hpp" in cmd_lower):
            return json.dumps(
                {
                    "command": command,
                    "status": "blocked",
                    "error": "Recursive findstr over source tree is blocked due to frequent timeouts.",
                    "hint": "Use rg_search_text(query, ...) instead.",
                },
                ensure_ascii=False,
            )

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                timeout=15,
            )

            stdout = _decode_output(result.stdout, command)
            stderr = _decode_output(result.stderr, command)

            return json.dumps(
                {
                    "command": command,
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": result.returncode,
                    "status": "success" if result.returncode == 0 else "error",
                }
            )

        except subprocess.TimeoutExpired as e:
            stdout = _decode_output(e.stdout, command)
            stderr = _decode_output(e.stderr, command)

            return json.dumps(
                {
                    "command": command,
                    "stdout": stdout,
                    "stderr": stderr,
                    "error": "Command execution timed out after 15 seconds.",
                    "status": "timeout",
                }
            )

    except Exception as e:
        return json.dumps(
            {
                "command": command,
                "error": str(e),
                "status": "exception",
            }
        )


execute_console_command_declaration = {
    "type": "function",
    "function": {
        "name": "execute_console_command",
        "description": "Execute a shell command on the local machine. Prefer structured tools (rg_search_text/rg_list_files) for file and text search.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The command to execute (e.g., 'dir', 'git status', 'python --version')",
                }
            },
            "required": ["command"],
        },
    },
}
