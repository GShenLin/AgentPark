import os
import subprocess
import threading
import time
from dataclasses import dataclass


@dataclass
class PipeReader:
    thread: threading.Thread
    chunks: list[bytes]
    errors: list[BaseException]


def powershell_utf8_script(command: str) -> str:
    return (
        "$__AgentParkUtf8 = [System.Text.UTF8Encoding]::new($false); "
        "[Console]::InputEncoding = $__AgentParkUtf8; "
        "[Console]::OutputEncoding = $__AgentParkUtf8; "
        "$OutputEncoding = $__AgentParkUtf8; "
        "& {\n"
        f"{str(command)}\n"
        "if (-not $?) { "
        "if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; "
        "exit 1 "
        "}\n"
        "}\n"
        "exit 0"
    )


def terminate_process(proc: subprocess.Popen | None) -> None:
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


def start_process_pipe_readers(
    proc: subprocess.Popen,
) -> tuple[PipeReader | None, PipeReader | None]:
    stdout_reader = (
        _start_pipe_reader(proc.stdout, name="console-stdout-reader")
        if proc.stdout is not None
        else None
    )
    stderr_reader = (
        _start_pipe_reader(proc.stderr, name="console-stderr-reader")
        if proc.stderr is not None
        else None
    )
    return stdout_reader, stderr_reader


def collect_process_output(
    proc: subprocess.Popen,
    stdout_reader: PipeReader | None,
    stderr_reader: PipeReader | None,
) -> tuple[bytes, bytes]:
    cleaned_process_tree = False

    def cleanup_process_tree_once() -> None:
        nonlocal cleaned_process_tree
        if cleaned_process_tree:
            return
        cleaned_process_tree = True
        terminate_process(proc)

    stdout_raw = _collect_pipe_reader(
        stdout_reader,
        stream_name="stdout",
        on_timeout=cleanup_process_tree_once,
    )
    stderr_raw = _collect_pipe_reader(
        stderr_reader,
        stream_name="stderr",
        on_timeout=cleanup_process_tree_once,
    )
    return stdout_raw, stderr_raw


def _terminate_windows_process_tree(proc: subprocess.Popen) -> None:
    pid = int(getattr(proc, "pid", 0) or 0)
    if pid <= 0:
        _terminate_process_fallback(proc)
        return

    descendant_pids = _windows_descendant_process_ids(pid)
    for process_id in [pid, *descendant_pids]:
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
        try:
            process_id = int(line.strip())
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


def _start_pipe_reader(pipe, *, name: str) -> PipeReader:
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
    return PipeReader(thread=thread, chunks=chunks, errors=errors)


def _join_pipe_reader(
    reader: PipeReader,
    *,
    total_timeout: float = 5.0,
    poll_interval: float = 0.05,
) -> bool:
    deadline = time.monotonic() + total_timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        reader.thread.join(timeout=min(remaining, poll_interval))
        if not reader.thread.is_alive():
            return True
    return not reader.thread.is_alive()


def _collect_pipe_reader(
    reader: PipeReader | None,
    *,
    stream_name: str,
    on_timeout=None,
) -> bytes:
    if reader is None:
        return b""
    finished = _join_pipe_reader(reader, total_timeout=5.0)
    if not finished and callable(on_timeout):
        on_timeout()
        _join_pipe_reader(reader, total_timeout=1.0)
    if reader.errors:
        error = reader.errors[0]
        raise RuntimeError(
            f"{stream_name} reader failed: {type(error).__name__}: {error}"
        ) from error
    return b"".join(reader.chunks)
