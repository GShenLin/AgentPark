import json
import os
import tempfile

from functions.console_tools import (
    execute_console_command,
    execute_console_command_declaration,
)
from functions.curl_tools import (
    execute_curl_command,
    execute_curl_command_declaration,
)
from functions.file_read_tools import (
    read_file,
    read_file_declaration,
)
from functions.file_write_tools import (
    write_file,
    write_file_declaration,
)
from functions.multi_tool_use_tools import (
    multi_tool_use_parallel,
    multi_tool_use_parallel_declaration,
)
from functions.rg_tools import (
    rg_list_files,
    rg_list_files_declaration,
    rg_search_text,
    rg_search_text_declaration,
)
from src.providers.agent_environment_context import resolve_agent_relative_path
from src.tool.tool_json_response import tool_json_error

_SECTION_PREFIX = "*** "
_BEGIN_MARKER = "*** Begin Patch"
_END_MARKER = "*** End Patch"
_ADD_PREFIX = "*** Add File: "
_UPDATE_PREFIX = "*** Update File: "
_DELETE_PREFIX = "*** Delete File: "
_MOVE_PREFIX = "*** Move to: "
_HUNK_PREFIX = "@@"
_VALID_HUNK_PREFIXES = {" ", "-", "+"}


class PatchApplyError(Exception):
    pass


def _resolve_path(file_path, agent=None):
    if not isinstance(file_path, str) or not file_path.strip():
        raise PatchApplyError("Patch file path must be a non-empty string.")
    return resolve_agent_relative_path(file_path.strip(), agent=agent)


def _is_section_line(line):
    return isinstance(line, str) and line.startswith(_SECTION_PREFIX)


def _parse_add_file(lines, index, file_path):
    content_lines = []
    while index < len(lines):
        line = lines[index]
        if _is_section_line(line):
            break
        if not line.startswith("+"):
            raise PatchApplyError(f"Add File body for {file_path!r} must contain only '+' lines.")
        content_lines.append(line[1:])
        index += 1
    return {"type": "add", "path": file_path, "lines": content_lines}, index


def _parse_hunk(lines, index, file_path):
    header = lines[index][len(_HUNK_PREFIX):].strip()
    hunk_lines = []
    index += 1
    while index < len(lines):
        line = lines[index]
        if _is_section_line(line) or line.startswith(_HUNK_PREFIX):
            break
        if not line or line[0] not in _VALID_HUNK_PREFIXES:
            raise PatchApplyError(
                f"Update hunk for {file_path!r} must contain only context, '-' or '+' lines."
            )
        hunk_lines.append((line[0], line[1:]))
        index += 1
    if not hunk_lines:
        raise PatchApplyError(f"Update hunk for {file_path!r} is empty.")
    return {"header": header, "lines": hunk_lines}, index


def _parse_update_file(lines, index, file_path):
    move_to = None
    hunks = []
    while index < len(lines):
        line = lines[index]
        if line.startswith(_MOVE_PREFIX):
            if move_to is not None:
                raise PatchApplyError(f"Update File {file_path!r} contains multiple Move to directives.")
            move_to = line[len(_MOVE_PREFIX):].strip()
            if not move_to:
                raise PatchApplyError(f"Move to directive for {file_path!r} is empty.")
            index += 1
            continue
        if line.startswith(_HUNK_PREFIX):
            hunk, index = _parse_hunk(lines, index, file_path)
            hunks.append(hunk)
            continue
        if _is_section_line(line):
            break
        raise PatchApplyError(f"Unexpected line in Update File {file_path!r}: {line!r}")
    return {"type": "update", "path": file_path, "move_to": move_to, "hunks": hunks}, index


def _parse_patch(patch):
    if not isinstance(patch, str) or not patch.strip():
        raise PatchApplyError("patch must be a non-empty string.")

    lines = patch.splitlines()
    if not lines or lines[0].strip() != _BEGIN_MARKER:
        raise PatchApplyError("Patch must start with '*** Begin Patch'.")
    if lines[-1].strip() != _END_MARKER:
        raise PatchApplyError("Patch must end with '*** End Patch'.")

    operations = []
    index = 1
    end_index = len(lines) - 1
    while index < end_index:
        line = lines[index]
        if not line:
            index += 1
            continue
        if line.startswith(_ADD_PREFIX):
            file_path = line[len(_ADD_PREFIX):].strip()
            operation, index = _parse_add_file(lines, index + 1, file_path)
            operations.append(operation)
            continue
        if line.startswith(_UPDATE_PREFIX):
            file_path = line[len(_UPDATE_PREFIX):].strip()
            operation, index = _parse_update_file(lines, index + 1, file_path)
            operations.append(operation)
            continue
        if line.startswith(_DELETE_PREFIX):
            file_path = line[len(_DELETE_PREFIX):].strip()
            operations.append({"type": "delete", "path": file_path})
            index += 1
            continue
        raise PatchApplyError(f"Unknown patch section: {line!r}")

    if not operations:
        raise PatchApplyError("Patch does not contain any file operations.")
    return operations


def _read_text_file(file_path, encoding):
    with open(file_path, "r", encoding=encoding, errors="replace") as handle:
        return handle.read()


def _file_exists_in_state(file_path, state):
    if file_path in state:
        return state[file_path] is not None
    return os.path.exists(file_path)


def _load_text_from_state(file_path, state, encoding):
    if file_path in state:
        value = state[file_path]
        if value is None:
            return False, ""
        return True, value
    if not os.path.isfile(file_path):
        return False, ""
    return True, _read_text_file(file_path, encoding)


def _lines_to_text(lines, trailing_newline=True):
    if not lines:
        return ""
    text = "\n".join(lines)
    if trailing_newline:
        text += "\n"
    return text


def _text_to_lines(text):
    return text.splitlines(), text.endswith(("\n", "\r"))


def _find_block(lines, block, start):
    if not block:
        return start
    last_start = len(lines) - len(block)
    for index in range(max(0, start), last_start + 1):
        if lines[index:index + len(block)] == block:
            return index
    return None


def _format_hunk_header(hunk):
    header = hunk.get("header") or ""
    return f" near {header!r}" if header else ""


def _apply_hunks(file_path, original_text, hunks):
    lines, trailing_newline = _text_to_lines(original_text)
    cursor = 0

    for hunk in hunks:
        old_block = [text for prefix, text in hunk["lines"] if prefix in {" ", "-"}]
        new_block = [text for prefix, text in hunk["lines"] if prefix in {" ", "+"}]
        position = _find_block(lines, old_block, cursor)
        if position is None:
            raise PatchApplyError(
                f"Could not locate update hunk in {file_path!r}{_format_hunk_header(hunk)}."
            )
        lines[position:position + len(old_block)] = new_block
        cursor = position + len(new_block)

    return _lines_to_text(lines, trailing_newline=trailing_newline)


def _simulate_operations(operations, encoding, *, agent=None):
    state = {}
    changed_paths = set()
    summaries = []

    for operation in operations:
        op_type = operation["type"]
        source_path = _resolve_path(operation["path"], agent=agent)

        if op_type == "add":
            if _file_exists_in_state(source_path, state):
                raise PatchApplyError(f"Add File target already exists: {source_path}")
            text = _lines_to_text(operation["lines"], trailing_newline=True)
            state[source_path] = text
            changed_paths.add(source_path)
            summaries.append({"type": "add", "path": source_path})
            continue

        if op_type == "delete":
            exists, _ = _load_text_from_state(source_path, state, encoding)
            if not exists:
                raise PatchApplyError(f"Delete File target does not exist: {source_path}")
            state[source_path] = None
            changed_paths.add(source_path)
            summaries.append({"type": "delete", "path": source_path})
            continue

        if op_type == "update":
            exists, text = _load_text_from_state(source_path, state, encoding)
            if not exists:
                raise PatchApplyError(f"Update File target does not exist: {source_path}")
            if not operation["hunks"] and operation.get("move_to") is None:
                raise PatchApplyError(f"Update File {source_path!r} must contain at least one hunk or Move to directive.")
            new_text = _apply_hunks(source_path, text, operation["hunks"]) if operation["hunks"] else text
            destination = operation.get("move_to")
            if destination:
                destination_path = _resolve_path(destination, agent=agent)
                if destination_path != source_path and _file_exists_in_state(destination_path, state):
                    raise PatchApplyError(f"Move target already exists: {destination_path}")
                state[source_path] = None
                state[destination_path] = new_text
                changed_paths.update({source_path, destination_path})
                summaries.append({"type": "update", "path": source_path, "move_to": destination_path})
            else:
                state[source_path] = new_text
                changed_paths.add(source_path)
                summaries.append({"type": "update", "path": source_path})
            continue

        raise PatchApplyError(f"Unsupported operation type: {op_type}")

    return state, changed_paths, summaries


def _ensure_parent_dir(file_path):
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _atomic_write(file_path, content, encoding):
    _ensure_parent_dir(file_path)
    parent = os.path.dirname(file_path) or "."
    temp_path = None
    try:
        fd, temp_path = tempfile.mkstemp(prefix=".aitools_patch_", dir=parent)
        with os.fdopen(fd, "w", encoding=encoding, errors="replace") as handle:
            handle.write(content)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except Exception:
                pass
        os.replace(temp_path, file_path)
        temp_path = None
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except Exception:
                pass


def _commit_state(state, encoding):
    for file_path, content in state.items():
        if content is None and os.path.exists(file_path):
            os.remove(file_path)

    for file_path, content in state.items():
        if content is not None:
            _atomic_write(file_path, content, encoding)


def apply_patch(patch, encoding="utf-8", agent=None):
    """
    Apply a Codex-style file patch to the local filesystem.
    """
    try:
        if not isinstance(encoding, str) or not encoding.strip():
            encoding = "utf-8"
        operations = _parse_patch(patch)
        state, changed_paths, summaries = _simulate_operations(operations, encoding.strip(), agent=agent)
        _commit_state(state, encoding.strip())
        return json.dumps(
            {
                "status": "success",
                "operations": summaries,
                "files_changed": sorted(changed_paths),
                "operation_count": len(summaries),
                "message": "Patch applied successfully.",
            },
            ensure_ascii=False,
        )
    except PatchApplyError as exc:
        return tool_json_error(str(exc))
    except Exception as exc:
        return tool_json_error(f"{type(exc).__name__}: {str(exc)}", exception_type=type(exc).__name__)


apply_patch_declaration = {
    "type": "function",
    "function": {
        "name": "apply_patch",
        "description": (
            "Apply a Codex-style patch to local files. The patch string must use "
            "*** Begin Patch / *** End Patch and Add File, Update File, Delete File sections."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": "Patch text to apply.",
                },
                "encoding": {
                    "type": "string",
                    "description": "Text encoding for reading and writing files (default: utf-8).",
                    "default": "utf-8",
                },
            },
            "required": ["patch"],
        },
    },
}

tool_function_aliases = {
    "multi_tool_use_parallel": ["multi_tool_use.parallel"],
}

__all__ = [
    "apply_patch",
    "apply_patch_declaration",
    "execute_console_command",
    "execute_console_command_declaration",
    "execute_curl_command",
    "execute_curl_command_declaration",
    "read_file",
    "read_file_declaration",
    "rg_search_text",
    "rg_search_text_declaration",
    "rg_list_files",
    "rg_list_files_declaration",
    "multi_tool_use_parallel",
    "multi_tool_use_parallel_declaration",
    "write_file",
    "write_file_declaration",
]
