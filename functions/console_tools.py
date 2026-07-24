import json
import subprocess
import time
from dataclasses import dataclass

from functions.console_completion_policy import ConsoleCommandProfile
from functions.console_completion_policy import analyze_console_completion
from functions.console_completion_policy import classify_console_command
from functions.console_output_policy import build_console_command_result
from functions.console_output_policy import resolve_tool_submission_char_limit
from functions.console_process_runtime import collect_process_output
from functions.console_process_runtime import powershell_utf8_script
from functions.console_process_runtime import start_process_pipe_readers
from functions.console_process_runtime import terminate_process
from functions.console_progress_watchdog import PytestProgressWatchdog
from src.providers.agent_environment_context import resolve_agent_working_directory
from src.runtime_cancellation import CancellationRequested, cancel_source_from_agent, raise_if_cancel_requested
from src.workspace_settings import load_workspace_settings


DEFAULT_CONSOLE_COMMAND_TIMEOUT_SECONDS = 120
MAX_CONSOLE_COMMAND_TIMEOUT_SECONDS = 3600
DEFAULT_CONSOLE_COMMAND_OUTPUT_CHARS = 131072
MAX_CONSOLE_COMMAND_OUTPUT_CHARS = 262144
MIN_PROGRESS_TIMEOUT_SECONDS = 5
MAX_PROGRESS_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class _ConsoleConfigValue:
    value: object
    field_name: str


def _parse_timeout_seconds(value, *, field_name: str = "timeout_seconds") -> int | None:
    if value is None or value == "":
        return DEFAULT_CONSOLE_COMMAND_TIMEOUT_SECONDS
    try:
        timeout = int(float(value))
    except Exception as exc:
        raise ValueError(f"{field_name} must be a number.") from exc
    if timeout <= 0:
        return None
    return max(1, min(timeout, MAX_CONSOLE_COMMAND_TIMEOUT_SECONDS))


def _resolve_command_timeout_seconds(
    timeout_seconds=None,
    agent=None,
    profile: ConsoleCommandProfile | None = None,
) -> int | None:
    if timeout_seconds is not None and timeout_seconds != "":
        resolved = _parse_timeout_seconds(timeout_seconds, field_name="timeout_seconds")
    else:
        configured = _find_console_config_value(
            agent,
            root_fields=("consoleCommandTimeoutSec", "console_command_timeout_sec"),
            section_fields={
                "consoleCommand": ("timeoutSec", "timeout_seconds"),
                "console_command": ("timeout_sec", "timeoutSeconds"),
            },
        )
        if configured is not None:
            resolved = _parse_timeout_seconds(configured.value, field_name=configured.field_name)
        else:
            resolved = DEFAULT_CONSOLE_COMMAND_TIMEOUT_SECONDS

    minimum_timeout = profile.minimum_timeout_seconds if profile else None
    if resolved is not None and minimum_timeout is not None and resolved < minimum_timeout:
        return minimum_timeout
    return resolved


def _resolve_progress_timeout_seconds(
    progress_timeout_seconds,
    *,
    profile: ConsoleCommandProfile,
    command_timeout_seconds: int | None,
) -> float | None:
    if progress_timeout_seconds is None or progress_timeout_seconds == "":
        return None
    if profile.completion_kind != "pytest":
        raise ValueError(
            "progress_timeout_seconds is supported only for pytest test runs"
        )
    if isinstance(progress_timeout_seconds, bool) or not isinstance(
        progress_timeout_seconds,
        (int, float),
    ):
        raise ValueError("progress_timeout_seconds must be a number")
    parsed = float(progress_timeout_seconds)
    if not (
        MIN_PROGRESS_TIMEOUT_SECONDS
        <= parsed
        <= MAX_PROGRESS_TIMEOUT_SECONDS
    ):
        raise ValueError(
            "progress_timeout_seconds must be between "
            f"{MIN_PROGRESS_TIMEOUT_SECONDS} and {MAX_PROGRESS_TIMEOUT_SECONDS}"
        )
    if (
        command_timeout_seconds is not None
        and parsed >= command_timeout_seconds
    ):
        raise ValueError(
            "progress_timeout_seconds must be less than the command timeout"
        )
    return parsed


def _parse_output_char_limit(value, *, field_name: str) -> int:
    if value is None or value == "":
        return DEFAULT_CONSOLE_COMMAND_OUTPUT_CHARS
    try:
        limit = int(float(value))
    except Exception as exc:
        raise ValueError(f"{field_name} must be a number.") from exc
    if limit <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
    return max(1, min(limit, MAX_CONSOLE_COMMAND_OUTPUT_CHARS))


def _resolve_command_output_char_limit(agent=None) -> int:
    configured = _find_console_config_value(
        agent,
        root_fields=("consoleCommandOutputMaxChars", "console_command_output_max_chars"),
        section_fields={
            "consoleCommand": ("outputMaxChars", "output_max_chars", "maxOutputChars", "max_output_chars"),
            "console_command": ("output_max_chars", "outputMaxChars", "max_output_chars", "maxOutputChars"),
        },
    )
    if configured is not None:
        return _parse_output_char_limit(configured.value, field_name=configured.field_name)
    return DEFAULT_CONSOLE_COMMAND_OUTPUT_CHARS


def _iter_console_config_sources(agent=None):
    agent_config = getattr(agent, "config", None)
    if isinstance(agent_config, dict):
        yield "agent.config", agent_config
    workspace_config = load_workspace_settings()
    if isinstance(workspace_config, dict):
        yield "config/config.json", workspace_config


def _find_console_config_value(agent=None, *, root_fields, section_fields) -> _ConsoleConfigValue | None:
    for source_name, payload in _iter_console_config_sources(agent):
        for field in root_fields:
            if field in payload:
                return _ConsoleConfigValue(payload.get(field), f"{source_name}.{field}")
        for section_name, fields in section_fields.items():
            section = payload.get(section_name)
            if not isinstance(section, dict):
                continue
            for field in fields:
                if field in section:
                    return _ConsoleConfigValue(section.get(field), f"{source_name}.{section_name}.{field}")
    return None


def _decode_output(data: bytes | None) -> str:
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "PowerShell output violated the UTF-8 console protocol "
            f"at byte {exc.start}; output was not replaced or guessed"
        ) from exc


def _build_console_command_result(
    *,
    command,
    stdout: str,
    stderr: str,
    status: str,
    agent=None,
    returncode=None,
    error: str | None = None,
    extra: dict | None = None,
) -> str:
    output_limit = _resolve_command_output_char_limit(agent)
    return build_console_command_result(
        command=command,
        stdout=stdout,
        stderr=stderr,
        status=status,
        output_limit=output_limit,
        submission_limit=resolve_tool_submission_char_limit(agent),
        returncode=returncode,
        error=error,
        extra=extra,
    )


def _resolve_command_cwd(agent) -> str | None:
    return resolve_agent_working_directory(agent)


def execute_console_command(
    command,
    timeout_seconds=None,
    progress_timeout_seconds=None,
    agent=None,
):
    """
    Executes a console command and returns the output.
    Uses a configurable timeout. If it times out, returns captured output so far (if possible) or a timeout message.
    """
    try:
        profile = classify_console_command(command)
        if profile.blocked:
            return json.dumps(
                {
                    "command": command,
                    "status": "blocked",
                    "error": profile.block_error,
                    "hint": profile.hint,
                },
                ensure_ascii=False,
            )

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
            cancel_source = cancel_source_from_agent(agent)
            command_timeout = _resolve_command_timeout_seconds(timeout_seconds, agent, profile=profile)
            progress_timeout = _resolve_progress_timeout_seconds(
                progress_timeout_seconds,
                profile=profile,
                command_timeout_seconds=command_timeout,
            )
            cwd = _resolve_command_cwd(agent)
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", powershell_utf8_script(str(command))],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
            )
            stdout_reader, stderr_reader = start_process_pipe_readers(proc)
            started_at = time.monotonic()
            deadline = started_at + command_timeout if command_timeout is not None else None
            progress_watchdog = (
                PytestProgressWatchdog(
                    stdout_chunks=stdout_reader.chunks,
                    timeout_seconds=progress_timeout,
                    started_at=started_at,
                )
                if progress_timeout is not None and stdout_reader is not None
                else None
            )
            while proc.poll() is None:
                try:
                    raise_if_cancel_requested(cancel_source)
                except CancellationRequested as e:
                    terminate_process(proc)
                    stdout_raw, stderr_raw = collect_process_output(proc, stdout_reader, stderr_reader)
                    return _build_console_command_result(
                        command=command,
                        stdout=_decode_output(stdout_raw),
                        stderr=_decode_output(stderr_raw),
                        status="stopped",
                        agent=agent,
                        error=str(e),
                        extra={"cwd": cwd} if cwd else None,
                    )
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    terminate_process(proc)
                    stdout_raw, stderr_raw = collect_process_output(proc, stdout_reader, stderr_reader)
                    stdout = _decode_output(stdout_raw)
                    stderr = _decode_output(stderr_raw)
                    timeout_label = f"{command_timeout} seconds" if command_timeout is not None else "disabled timeout"
                    status, completion_error, extra = analyze_console_completion(
                        stdout,
                        stderr,
                        "timeout",
                        profile,
                    )
                    return _build_console_command_result(
                        command=command,
                        stdout=stdout,
                        stderr=stderr,
                        status=status,
                        agent=agent,
                        error=completion_error or f"Command execution timed out after {timeout_label}.",
                        extra={**extra, **({"cwd": cwd} if cwd else {})},
                    )
                if progress_watchdog is not None:
                    progress_watchdog.observe(now=now)
                    if progress_watchdog.expired(now=now):
                        watchdog_payload = progress_watchdog.snapshot(now=now).to_payload()
                        terminate_process(proc)
                        stdout_raw, stderr_raw = collect_process_output(
                            proc,
                            stdout_reader,
                            stderr_reader,
                        )
                        return _build_console_command_result(
                            command=command,
                            stdout=_decode_output(stdout_raw),
                            stderr=_decode_output(stderr_raw),
                            status="no_progress_timeout",
                            agent=agent,
                            error=(
                                "Pytest produced no semantic test completion marker for "
                                f"{progress_timeout:g} seconds. The opt-in watchdog tracks "
                                "quiet progress glyph runs and verbose terminal statuses on "
                                "stdout; stderr activity does not reset it."
                            ),
                            extra={
                                "progress_watchdog": watchdog_payload,
                                **({"cwd": cwd} if cwd else {}),
                            },
                        )
                time.sleep(0.05)

            stdout_raw, stderr_raw = collect_process_output(proc, stdout_reader, stderr_reader)
            stdout = _decode_output(stdout_raw)
            stderr = _decode_output(stderr_raw)
            status = "success" if proc.returncode == 0 else "error"
            status, completion_error, extra = analyze_console_completion(stdout, stderr, status, profile)

            return _build_console_command_result(
                command=command,
                stdout=stdout,
                stderr=stderr,
                returncode=proc.returncode,
                status=status,
                agent=agent,
                error=completion_error,
                extra={**extra, **({"cwd": cwd} if cwd else {})},
            )

        except CancellationRequested as e:
            return _build_console_command_result(
                command=command,
                stdout="",
                stderr="",
                status="stopped",
                agent=agent,
                error=str(e),
            )
        except subprocess.TimeoutExpired as e:
            stdout = _decode_output(e.stdout)
            stderr = _decode_output(e.stderr)
            command_timeout = _resolve_command_timeout_seconds(timeout_seconds, agent, profile=profile)
            timeout_label = f"{command_timeout} seconds" if command_timeout is not None else "disabled timeout"
            status, completion_error, extra = analyze_console_completion(stdout, stderr, "timeout", profile)

            return _build_console_command_result(
                command=command,
                stdout=stdout,
                stderr=stderr,
                status=status,
                agent=agent,
                error=completion_error or f"Command execution timed out after {timeout_label}.",
                extra=extra,
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
        "description": (
            "Execute a shell command on the local machine. Prefer structured tools "
            "(rg_search_text/rg_list_files) for file and text search. Commands run through PowerShell "
            "with powershell -NoProfile -Command, so use PowerShell syntax such as Get-ChildItem, "
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
                    "description": "The PowerShell command to execute (e.g., 'Get-ChildItem', 'git status', 'python --version')",
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

execute_console_command.tool_timeout_seconds = 0
