import json
import locale
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass

from src.providers.agent_environment_context import resolve_agent_working_directory
from src.runtime_cancellation import CancellationRequested, cancel_source_from_agent, raise_if_cancel_requested
from src.workspace_settings import load_workspace_settings


DEFAULT_CONSOLE_COMMAND_TIMEOUT_SECONDS = 120
MAX_CONSOLE_COMMAND_TIMEOUT_SECONDS = 3600
DEFAULT_CONSOLE_COMMAND_OUTPUT_CHARS = 131072
MAX_CONSOLE_COMMAND_OUTPUT_CHARS = 262144


@dataclass(frozen=True)
class _ConsoleConfigValue:
    value: object
    field_name: str


@dataclass(frozen=True)
class _ConsoleCommandProfile:
    blocked: bool = False
    block_error: str = ""
    hint: str = ""
    minimum_timeout_seconds: int | None = None
    completion_kind: str = ""


@dataclass
class _PipeReader:
    thread: threading.Thread
    chunks: list[bytes]
    errors: list[BaseException]


def _classify_console_command(command) -> _ConsoleCommandProfile:
    command_text = str(command or "")
    command_lower = command_text.lower()

    if _looks_like_high_context_git_diff(command_lower):
        return _ConsoleCommandProfile(
            blocked=True,
            block_error="High-context git diff commands are blocked because they can produce output and still time out.",
            hint="Use 'git --no-pager diff --stat', '--numstat', '--name-only', or read narrow changed regions directly.",
        )

    if (
        "npx" in command_lower
        and "skills" in command_lower
        and "find" in command_lower
        and "--yes" not in command_lower
        and "npx -y" not in command_lower
    ):
        return _ConsoleCommandProfile(
            blocked=True,
            block_error="Interactive npx skill discovery is blocked because it can wait for package-install confirmation.",
            hint="Use 'npx --yes skills find ...' or 'npx -y skills find ...'.",
        )

    if _looks_like_broad_powershell_file_scan(command_lower):
        return _ConsoleCommandProfile(
            blocked=True,
            block_error="Broad recursive PowerShell file scans are blocked because they repeatedly time out in this workspace.",
            hint=(
                "Use rg_search_text for text search or rg_list_files for focused inventories."
            ),
        )

    if _looks_like_webui_build(command_lower):
        return _ConsoleCommandProfile(minimum_timeout_seconds=540, completion_kind="webui_build")

    if _looks_like_pytest_collect(command_lower):
        return _ConsoleCommandProfile(minimum_timeout_seconds=180, completion_kind="pytest_collect")

    if _looks_like_pytest_run(command_lower):
        return _ConsoleCommandProfile(minimum_timeout_seconds=300, completion_kind="pytest")

    return _ConsoleCommandProfile()


def _looks_like_high_context_git_diff(command_lower: str) -> bool:
    if "git" not in command_lower or "diff" not in command_lower:
        return False
    for match in re.finditer(r"--unified[=\s]+(\d+)|-u\s*(\d+)", command_lower):
        value = match.group(1) or match.group(2)
        try:
            if int(value) > 20:
                return True
        except Exception:
            continue
    return False


def _looks_like_broad_powershell_file_scan(command_lower: str) -> bool:
    has_recursive_ps_listing = (
        ("get-childitem" in command_lower or re.search(r"(^|\W)gci(\W|$)", command_lower))
        and "-recurse" in command_lower
    )
    has_content_line_count = "measure-object" in command_lower and "get-content" in command_lower
    has_rg_file_content_count = bool(
        "measure-object" in command_lower
        and "get-content" in command_lower
        and re.search(r"\brg(\.exe)?\s+--files\b", command_lower)
    )
    return bool((has_recursive_ps_listing and has_content_line_count) or has_rg_file_content_count)


def _looks_like_webui_build(command_lower: str) -> bool:
    return "npm" in command_lower and "run" in command_lower and "build" in command_lower


def _looks_like_pytest_collect(command_lower: str) -> bool:
    return "pytest" in command_lower and "--collect-only" in command_lower


def _looks_like_pytest_run(command_lower: str) -> bool:
    return "pytest" in command_lower


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
    profile: _ConsoleCommandProfile | None = None,
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


def _tail_limit_stream_text(text: str, *, stream_name: str, limit: int) -> tuple[str, dict]:
    value = str(text or "")
    original_chars = len(value)
    if original_chars <= limit:
        return value, {
            "truncated": False,
            "original_chars": original_chars,
            "returned_chars": original_chars,
        }
    return value[-limit:], {
        "truncated": True,
        "original_chars": original_chars,
        "returned_chars": limit,
        "omitted_chars": original_chars - limit,
        "strategy": "tail",
        "notice": (
            f"{stream_name} exceeded the hard limit of {limit} characters; "
            f"only the tail of this stream is returned."
        ),
    }


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
    stdout, stdout_meta = _tail_limit_stream_text(stdout, stream_name="stdout", limit=output_limit)
    stderr, stderr_meta = _tail_limit_stream_text(stderr, stream_name="stderr", limit=output_limit)
    result = {
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "status": status,
    }
    if returncode is not None:
        result["returncode"] = returncode
    if error is not None:
        result["error"] = error
    if isinstance(extra, dict) and extra:
        result.update(extra)

    result.update(
        {
            "stdout_truncated": stdout_meta["truncated"],
            "stdout_original_chars": stdout_meta["original_chars"],
            "stdout_returned_chars": stdout_meta["returned_chars"],
            "stderr_truncated": stderr_meta["truncated"],
            "stderr_original_chars": stderr_meta["original_chars"],
            "stderr_returned_chars": stderr_meta["returned_chars"],
            "output_max_chars_per_stream": output_limit,
        }
    )
    truncated_streams = []
    if stdout_meta["truncated"]:
        truncated_streams.append({"stream": "stdout", **stdout_meta})
    if stderr_meta["truncated"]:
        truncated_streams.append({"stream": "stderr", **stderr_meta})
    if truncated_streams:
        result["output_truncated"] = True
        result["output_truncation_notice"] = (
            "Command output exceeded the hard stdout/stderr size limit. "
            "The returned stdout/stderr fields are partial and contain only tail content for truncated streams."
        )
        result["output_truncation"] = {
            "max_chars_per_stream": output_limit,
            "streams": truncated_streams,
        }
    return json.dumps(result, ensure_ascii=False)


def _resolve_command_cwd(agent) -> str | None:
    return resolve_agent_working_directory(agent)


def _analyze_console_completion(command, stdout: str, stderr: str, status: str, profile: _ConsoleCommandProfile):
    extra: dict = {}
    final_status = status
    error = None
    combined_output = f"{stdout or ''}\n{stderr or ''}"
    combined_lower = combined_output.lower()

    if profile.completion_kind == "webui_build":
        completed = bool(re.search(r"\bbuilt in\s+\d", combined_lower) or "vite" in combined_lower and "built in" in combined_lower)
        extra["detected_completion"] = {
            "kind": "webui_build",
            "completed": completed,
        }
        if status == "timeout" and completed:
            final_status = "partial_success_timeout"
            error = "Command timed out after output that matches a completed WebUI build."

    elif profile.completion_kind == "pytest_collect":
        match = re.search(r"(\d+)\s+tests?\s+collected", combined_lower)
        completed = match is not None
        details = {
            "kind": "pytest_collect",
            "completed": completed,
        }
        if match:
            details["collected_tests"] = int(match.group(1))
        extra["detected_completion"] = details
        if status == "timeout" and completed:
            final_status = "partial_success_timeout"
            error = "Command timed out after pytest reported completed collection."

    return final_status, error, extra


def _terminate_process(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    if os.name == "nt":
        _terminate_windows_process_tree(proc)
        return
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=0.5)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=0.5)
        except Exception:
            pass


def _terminate_windows_process_tree(proc: subprocess.Popen) -> None:
    pid = int(getattr(proc, "pid", 0) or 0)
    if pid <= 0:
        _terminate_process_fallback(proc)
        return

    descendant_pids = _windows_descendant_process_ids(pid)
    taskkill_pids = [pid, *descendant_pids]
    for process_id in taskkill_pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process_id), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            continue

    try:
        proc.wait(timeout=0.5)
    except Exception:
        _terminate_process_fallback(proc)


def _windows_descendant_process_ids(root_pid: int) -> list[int]:
    script = (
        "$root = [int]$args[0]; "
        "$items = Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId; "
        "$known = @{}; "
        "$known[$root] = $true; "
        "$added = $true; "
        "while ($added) { "
        "  $added = $false; "
        "  foreach ($item in $items) { "
        "    $processId = [int]$item.ProcessId; "
        "    $parent = [int]$item.ParentProcessId; "
        "    if ($known.ContainsKey($parent) -and -not $known.ContainsKey($processId)) { "
        "      $known[$processId] = $true; "
        "      $added = $true; "
        "    } "
        "  } "
        "} "
        "$known.Keys | Where-Object { $_ -ne $root } | Sort-Object"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script, str(root_pid)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:
        return []
    if completed.returncode != 0:
        return []
    process_ids: list[int] = []
    for line in str(completed.stdout or "").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            process_id = int(text)
        except ValueError:
            continue
        if process_id > 0 and process_id != root_pid:
            process_ids.append(process_id)
    return process_ids


def _terminate_process_fallback(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=0.5)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=0.5)
        except Exception:
            pass


def _start_pipe_reader(pipe, *, name: str) -> _PipeReader:
    chunks: list[bytes] = []
    errors: list[BaseException] = []

    def _read_pipe() -> None:
        try:
            while True:
                data = pipe.read(8192)
                if not data:
                    break
                chunks.append(data)
        except BaseException as exc:
            errors.append(exc)
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    thread = threading.Thread(target=_read_pipe, daemon=True, name=name)
    thread.start()
    return _PipeReader(thread=thread, chunks=chunks, errors=errors)


def _start_process_pipe_readers(proc: subprocess.Popen) -> tuple[_PipeReader | None, _PipeReader | None]:
    stdout_reader = _start_pipe_reader(proc.stdout, name="console-stdout-reader") if proc.stdout is not None else None
    stderr_reader = _start_pipe_reader(proc.stderr, name="console-stderr-reader") if proc.stderr is not None else None
    return stdout_reader, stderr_reader


def _join_pipe_reader(reader: _PipeReader, *, total_timeout: float = 5.0, poll_interval: float = 0.05) -> bool:
    """Wait for a pipe reader thread to finish. Returns True if the thread finished, False on timeout.

    Windows child processes can delay pipe EOF briefly after the target process has exited
    (output flushing / handle inheritance). A single short join can race that flush, so we poll
    with a generous budget instead of failing immediately.
    """
    deadline = time.monotonic() + total_timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        reader.thread.join(timeout=min(remaining, poll_interval))
        if not reader.thread.is_alive():
            return True
    return not reader.thread.is_alive()


def _collect_pipe_reader(reader: _PipeReader | None, *, stream_name: str, on_timeout=None) -> bytes:
    if reader is None:
        return b""
    finished = _join_pipe_reader(reader, total_timeout=5.0)
    if not finished and callable(on_timeout):
        on_timeout()
        finished = _join_pipe_reader(reader, total_timeout=1.0)
    if reader.errors:
        error = reader.errors[0]
        raise RuntimeError(f"{stream_name} reader failed: {type(error).__name__}: {error}") from error
    if not finished:
        # Reader thread is still draining. We cannot block indefinitely here, but we also must not
        # discard data that was already captured. Return what we have; callers should treat this as
        # partial output (truncation metadata is added elsewhere for large streams).
        return b"".join(reader.chunks)
    return b"".join(reader.chunks)


def _collect_process_output(
    proc: subprocess.Popen,
    stdout_reader: _PipeReader | None,
    stderr_reader: _PipeReader | None,
) -> tuple[bytes, bytes]:
    cleaned_process_tree = False

    def cleanup_process_tree_once() -> None:
        nonlocal cleaned_process_tree
        if cleaned_process_tree:
            return
        cleaned_process_tree = True
        _terminate_process(proc)

    stdout_raw = _collect_pipe_reader(stdout_reader, stream_name="stdout", on_timeout=cleanup_process_tree_once)
    stderr_raw = _collect_pipe_reader(stderr_reader, stream_name="stderr", on_timeout=cleanup_process_tree_once)
    return stdout_raw, stderr_raw


def execute_console_command(command, timeout_seconds=None, agent=None):
    """
    Executes a console command and returns the output.
    Uses a configurable timeout. If it times out, returns captured output so far (if possible) or a timeout message.
    """
    try:
        profile = _classify_console_command(command)
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
            cwd = _resolve_command_cwd(agent)
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", str(command)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
            )
            stdout_reader, stderr_reader = _start_process_pipe_readers(proc)
            deadline = time.monotonic() + command_timeout if command_timeout is not None else None
            while proc.poll() is None:
                try:
                    raise_if_cancel_requested(cancel_source)
                except CancellationRequested as e:
                    _terminate_process(proc)
                    stdout_raw, stderr_raw = _collect_process_output(proc, stdout_reader, stderr_reader)
                    return _build_console_command_result(
                        command=command,
                        stdout=_decode_output(stdout_raw, command),
                        stderr=_decode_output(stderr_raw, command),
                        status="stopped",
                        agent=agent,
                        error=str(e),
                        extra={"cwd": cwd} if cwd else None,
                    )
                if deadline is not None and time.monotonic() >= deadline:
                    _terminate_process(proc)
                    stdout_raw, stderr_raw = _collect_process_output(proc, stdout_reader, stderr_reader)
                    stdout = _decode_output(stdout_raw, command)
                    stderr = _decode_output(stderr_raw, command)
                    timeout_label = f"{command_timeout} seconds" if command_timeout is not None else "disabled timeout"
                    status, completion_error, extra = _analyze_console_completion(
                        command,
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
                time.sleep(0.05)

            stdout_raw, stderr_raw = _collect_process_output(proc, stdout_reader, stderr_reader)
            stdout = _decode_output(stdout_raw, command)
            stderr = _decode_output(stderr_raw, command)
            status = "success" if proc.returncode == 0 else "error"
            status, completion_error, extra = _analyze_console_completion(command, stdout, stderr, status, profile)

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
            stdout = _decode_output(e.stdout, command)
            stderr = _decode_output(e.stderr, command)
            command_timeout = _resolve_command_timeout_seconds(timeout_seconds, agent, profile=profile)
            timeout_label = f"{command_timeout} seconds" if command_timeout is not None else "disabled timeout"
            status, completion_error, extra = _analyze_console_completion(command, stdout, stderr, "timeout", profile)

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
            "Large stdout/stderr values are hard-limited; truncated streams return tail content only with "
            "explicit truncation metadata."
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
                }
            },
            "required": ["command"],
        },
    },
}

execute_console_command.tool_timeout_seconds = 0
