import json
import os
import tempfile

from src.providers.agent_environment_context import resolve_agent_relative_path


_NO_CHANGE_COMPARE_MAX_BYTES = 4 * 1024 * 1024
_KNOWN_PARENT_DIRS = set()


def _classify_write_error(file_path, err):
    msg = str(err or "")
    low = msg.lower()
    status = "exception"
    retryable = False
    hint = None

    if isinstance(err, PermissionError):
        status = "locked_or_readonly"
    elif isinstance(err, OSError) and getattr(err, "errno", None) in (13, 30):
        status = "locked_or_readonly"

    markers = [
        "access is denied",
        "permission denied",
        "read-only",
        "readonly",
        "being used by another process",
        "used by another process",
    ]
    if any(m in low for m in markers):
        status = "locked_or_readonly"

    if status == "locked_or_readonly":
        hint = (
            "File may be read-only or locked (e.g. Perforce). "
            "Run 'p4 edit <file>' or unlock the file, then retry once."
        )

    return {
        "status": status,
        "file_path": file_path,
        "error": msg,
        "retryable": retryable,
        "hint": hint,
    }


def _ensure_parent_dir(file_path, ensure_dir):
    if not ensure_dir:
        return
    parent = os.path.dirname(file_path)
    if not parent:
        return
    parent = os.path.abspath(parent)
    if parent in _KNOWN_PARENT_DIRS:
        return
    os.makedirs(parent, exist_ok=True)
    _KNOWN_PARENT_DIRS.add(parent)


def _is_noop_write(file_path, content, encoding, append):
    if append:
        return False
    if not os.path.isfile(file_path):
        return False
    try:
        size = os.path.getsize(file_path)
    except Exception:
        return False
    if size > _NO_CHANGE_COMPARE_MAX_BYTES:
        return False
    try:
        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            existing = f.read()
        return existing == content
    except Exception:
        return False


def write_file(
    file_path,
    content,
    encoding="utf-8",
    append=False,
    ensure_dir=True,
    atomic=True,
    skip_if_unchanged=True,
    agent=None,
):
    """
    Writes text content to a file on the local filesystem.
    """
    temp_path = None
    try:
        if not isinstance(file_path, str) or not file_path.strip():
            return json.dumps({"file_path": file_path, "error": "Invalid file_path", "status": "error"})

        if content is None:
            content = ""
        elif not isinstance(content, str):
            content = str(content)

        target = resolve_agent_relative_path(file_path, agent=agent)
        append = bool(append)
        atomic = bool(atomic)
        skip_if_unchanged = bool(skip_if_unchanged)

        _ensure_parent_dir(target, ensure_dir=bool(ensure_dir))

        if skip_if_unchanged and _is_noop_write(target, content, encoding, append):
            return json.dumps(
                {
                    "status": "success",
                    "file_path": target,
                    "append": append,
                    "unchanged": True,
                    "chars_written": 0,
                    "bytes_written": 0,
                    "message": "Skipped write because file content is unchanged.",
                },
                ensure_ascii=False,
            )

        chars_written = 0
        if append:
            with open(target, "a", encoding=encoding, errors="replace") as f:
                chars_written = f.write(content)
        else:
            if atomic:
                parent = os.path.dirname(target) or "."
                fd, temp_path = tempfile.mkstemp(prefix=".aitools_tmp_", dir=parent)
                with os.fdopen(fd, "w", encoding=encoding, errors="replace") as f:
                    chars_written = f.write(content)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
                os.replace(temp_path, target)
                temp_path = None
            else:
                with open(target, "w", encoding=encoding, errors="replace") as f:
                    chars_written = f.write(content)

        try:
            bytes_written = len(content.encode(encoding, errors="replace"))
        except Exception:
            bytes_written = None

        return json.dumps(
            {
                "status": "success",
                "file_path": target,
                "append": append,
                "atomic": atomic and not append,
                "unchanged": False,
                "chars_written": chars_written,
                "bytes_written": bytes_written,
                "message": "File written successfully.",
            },
            ensure_ascii=False,
        )

    except Exception as e:
        if temp_path:
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return json.dumps(_classify_write_error(file_path, e), ensure_ascii=False)


write_file_declaration = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Write text content to a file on the local machine. Supports atomic overwrite and skipping unchanged writes for faster repeated tool calls.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file",
                },
                "content": {
                    "type": "string",
                    "description": "Text content to write",
                },
                "encoding": {
                    "type": "string",
                    "description": "Text encoding (default: utf-8)",
                    "default": "utf-8",
                },
                "append": {
                    "type": "boolean",
                    "description": "Append to the file instead of overwriting (default: false)",
                    "default": False,
                },
                "ensure_dir": {
                    "type": "boolean",
                    "description": "Create parent directories if missing (default: true)",
                    "default": True,
                },
                "atomic": {
                    "type": "boolean",
                    "description": "Use atomic replace for non-append writes (default: true).",
                    "default": True,
                },
                "skip_if_unchanged": {
                    "type": "boolean",
                    "description": "Skip non-append writes when target content is unchanged (default: true).",
                    "default": True,
                },
            },
            "required": ["file_path", "content"],
        },
    },
}
