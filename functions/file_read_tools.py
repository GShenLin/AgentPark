import json
import os

from functions.tool_output_limits import resolve_tool_result_char_limit
from src.providers.agent_environment_context import resolve_agent_relative_path
from src.runtime_cancellation import CancellationRequested, cancel_source_from_agent, raise_if_cancel_requested


_READ_FILE_MAX_CHARS = 20000
_READ_FILE_METADATA_RESERVE_CHARS = 1200


def read_file(file_path, start_line=1, end_line=None, agent=None):
    """
    Reads a file from the local filesystem.
    """
    try:
        if not isinstance(file_path, str) or not file_path.strip():
            return json.dumps({"file_path": file_path, "error": "Invalid file_path", "status": "error"})
        target = resolve_agent_relative_path(file_path, agent=agent)
        if not os.path.exists(target):
            basename = os.path.basename(target)
            return json.dumps({
                "file_path": target,
                "error": "File not found",
                "status": "error",
                "next_action": (
                    "Use rg_list_files from the working root with "
                    f"include_globs=['**/{basename}'] to locate a moved file."
                ),
            }, ensure_ascii=False)

        try:
            start_line = int(start_line)
        except Exception:
            start_line = 1
        if start_line < 1:
            start_line = 1

        if end_line is not None:
            try:
                end_line = int(end_line)
            except Exception:
                end_line = None
            if isinstance(end_line, int) and end_line < start_line:
                end_line = start_line

        selected_lines = []
        selected_chars = 0
        total_lines = 0
        output_truncated = False
        next_start_line = None
        result_char_limit = resolve_tool_result_char_limit(agent, _READ_FILE_MAX_CHARS)
        content_char_limit = max(1, result_char_limit - _READ_FILE_METADATA_RESERVE_CHARS)

        cancel_source = cancel_source_from_agent(agent)
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, start=1):
                raise_if_cancel_requested(cancel_source)
                total_lines = line_no
                if line_no < start_line:
                    continue
                if end_line is not None and line_no > end_line:
                    continue

                line_len = len(line)
                if selected_chars + line_len > content_char_limit:
                    remaining = content_char_limit - selected_chars
                    if remaining > 0:
                        selected_lines.append(line[:remaining])
                        selected_chars += remaining
                    output_truncated = True
                    next_start_line = line_no + 1
                    break

                selected_lines.append(line)
                selected_chars += line_len

        content = "".join(selected_lines)
        if output_truncated:
            content += "\n...(truncated)...\n"

        if selected_lines:
            read_end = start_line + len(selected_lines) - 1
        else:
            read_end = min(total_lines, start_line) if total_lines else start_line
        if end_line is not None:
            read_end = min(read_end, end_line)

        payload = {
            "file_path": target,
            "content": content,
            "total_lines": total_lines,
            "read_lines": f"{start_line}-{read_end}",
            "status": "success",
        }
        if output_truncated:
            payload["output_truncated"] = True
            payload["output_char_limit"] = result_char_limit
            payload["next_start_line"] = next_start_line
        return json.dumps(payload, ensure_ascii=False)

    except CancellationRequested as e:
        return json.dumps({"file_path": file_path, "error": str(e), "status": "stopped"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"file_path": file_path, "error": str(e), "status": "exception"}, ensure_ascii=False)


read_file_declaration = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read text content from a file, with optional line range and output truncation. For local images, including images referenced in Markdown, use view_image to see their contents.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Start line number (1-based, default: 1)",
                    "default": 1,
                },
                "end_line": {
                    "type": "integer",
                    "description": "End line number (optional, default: end of file)",
                },
            },
            "required": ["file_path"],
        },
    },
}


