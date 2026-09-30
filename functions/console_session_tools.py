"""Model-facing process sessions. Waiting never changes the execution deadline."""

import json

from functions.console_completion_policy import classify_console_command
from functions.console_output_policy import resolve_tool_submission_char_limit
from functions.console_session_registry import registry_for
from src.providers.agent_environment_context import resolve_agent_working_directory
from src.runtime_cancellation import CancellationRequested, cancel_source_from_agent


def _integer(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
    return value


def _serialize(session, cursor, max_chars, agent):
    limit = resolve_tool_submission_char_limit(agent)
    size = _integer(max_chars, "max_chars", 1, 65536)
    while True:
        result = json.dumps(session.snapshot(cursor, size), ensure_ascii=False)
        if limit is None or len(result) <= limit:
            return result
        if size == 1:
            raise ValueError("Session metadata exceeds toolResultSubmissionMaxChars")
        size = max(1, size // 2)


def _invoke(operation):
    try:
        return operation()
    except CancellationRequested as exc:
        return json.dumps({"status": "stopped", "error": str(exc)}, ensure_ascii=False)
    except ValueError as exc:
        return json.dumps({"status": "invalid_arguments", "error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"status": "exception", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)


def start_console_session(command, timeout_seconds=120, child_process_policy="error", agent=None):
    def run():
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        timeout = _integer(timeout_seconds, "timeout_seconds", 0, 3600)
        if child_process_policy not in ("error", "terminate"):
            raise ValueError("child_process_policy must be error or terminate")
        from src.runtime_environment import get_runtime_environment
        if child_process_policy != "error" and not get_runtime_environment().is_windows:
            raise ValueError("child_process_policy=terminate currently requires Windows job accounting")
        profile = classify_console_command(command)
        if profile.blocked:
            return json.dumps({"status": "blocked", "error": profile.block_error, "hint": profile.hint})
        lower = command.lower()
        if "findstr" in lower and "/s" in lower and any(ext in lower for ext in ("*.h", "*.cpp", "*.hpp")):
            return json.dumps({"status": "blocked", "error": "Use rg_search_text instead of recursive source findstr"})
        registry = registry_for(agent)
        session = registry.start(command=command, cwd=resolve_agent_working_directory(agent),
                                 timeout_seconds=timeout, cancel_source=cancel_source_from_agent(agent),
                                 child_process_policy=child_process_policy)
        # No output is consumed at launch. The first read starts at zero.
        return json.dumps({"session_id": session.session_id, "pid": session.proc.pid,
                           "cwd": session.cwd, "status": "running",
                           "next_cursor": {"session_id": session.session_id, "stdout": 0, "stderr": 0}})
    return _invoke(run)


def read_console_session(session_id, cursor=None, max_chars=8000, agent=None):
    return _invoke(lambda: _serialize(registry_for(agent).get(session_id), cursor, max_chars, agent))


def wait_console_session(session_id, cursor=None, wait_seconds=10, max_chars=8000, agent=None):
    def run():
        wait = _integer(wait_seconds, "wait_seconds", 0, 60)
        session = registry_for(agent).get(session_id)
        # Validate output arguments before waiting or triggering any cancellation.
        _serialize(session, cursor, max_chars, agent)
        session.wait(wait, cancel_source_from_agent(agent))
        return _serialize(session, cursor, max_chars, agent)
    return _invoke(run)


def stop_console_session(session_id, cursor=None, max_chars=8000, agent=None):
    def run():
        session = registry_for(agent).get(session_id)
        _serialize(session, cursor, max_chars, agent)
        session.stop_requested.set()
        if not session.done.wait(20):
            raise RuntimeError("Session cancellation has not completed")
        return _serialize(session, cursor, max_chars, agent)
    return _invoke(run)


_CURSOR = {"type": ["object", "null"], "properties": {
    "session_id": {"type": "string"},
    "stdout": {"type": "integer", "minimum": 0}, "stderr": {"type": "integer", "minimum": 0},
}, "required": ["session_id", "stdout", "stderr"], "additionalProperties": False}
_READ = {"session_id": {"type": "string"}, "cursor": _CURSOR,
         "max_chars": {"type": "integer", "minimum": 1, "maximum": 65536}}


def _declaration(name, description, properties, required):
    return {"type": "function", "function": {"name": name, "description": description,
        "parameters": {"type": "object", "properties": properties,
                       "required": required, "additionalProperties": False}}}


start_console_session_declaration = _declaration(
    "start_console_session",
    "Start a local noninteractive shell command and immediately return a process session ID. "
    "Prefer this for builds, tests and editor runs; launch the executable in the foreground inside the command. "
    "Use the environment_context shell. Windows uses UTF-8 PowerShell with terminating cmdlet errors; "
    "the final native exit code is preserved unless explicitly handled with exit 0. "
    "Do not detach children; this session owns the process tree. Windows GUI executables need an explicit wait: "
    "pipe their invocation to Out-Default, or use Start-Process -Wait -PassThru and exit with its ExitCode. "
    "A shell that exits leaving live children is an error and those children are terminated. "
    "On Windows, child_process_policy=terminate explicitly permits cleaning up known remaining helper processes "
    "after the foreground command exits; result records their count, and status then reflects the shell exit. "
    "Never use terminate to infer success for an asynchronously launched GUI task. Default policy is error. "
    "Read with read_console_session or wait_console_session. timeout_seconds is the total execution deadline "
    "(default 120, 0 disables it). Sessions are owned by this Agent run and stopped/cleaned at run end or Stop. "
    "Sessions do not persist across runs and currently do not support remote workers or stdin input.",
    {"command": {"type": "string"}, "timeout_seconds": {"type": "integer", "minimum": 0, "maximum": 3600},
     "child_process_policy": {"type": "string", "enum": ["error", "terminate"]}},
    ["command"],
)
read_console_session_declaration = _declaration(
    "read_console_session",
    "Read available stdout/stderr and process status without waiting. Pass the previous next_cursor to continue; "
    "omit cursor to replay from the beginning. max_chars limits each stream (default 8000). "
    "No output is silently discarded: has_more_output means read again, even after finished=true. "
    "A cursor is bound to one session. finished and returncode describe process completion, not test assertions.",
    _READ, ["session_id"],
)
wait_console_session_declaration = _declaration(
    "wait_console_session",
    "Wait up to wait_seconds (default 10, maximum 60) for command completion, then read output using the cursor. "
    "If still running, reuse session_id and next_cursor; an expired wait does NOT terminate the command. "
    "A finished command can still have unread output: drain while has_more_output is true.",
    {**_READ, "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 60}}, ["session_id"],
)
stop_console_session_declaration = _declaration(
    "stop_console_session", "Stop this run's process session and its children, wait for cleanup, and return remaining output. "
    "Already finished sessions retain their exit status. Use next_cursor to drain further output.", _READ, ["session_id"],
)

for _tool in (start_console_session, read_console_session, wait_console_session, stop_console_session):
    _tool.tool_timeout_seconds = 0
    _tool.tool_cooperative_cancellation = True
