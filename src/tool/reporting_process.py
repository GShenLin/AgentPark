"""subprocess.run semantics with a reporting interval instead of a kill deadline."""
import os
import subprocess
import time

from functions.console_process_runtime import terminate_process
from src.runtime_cancellation import current_tool_call_cancel_source, raise_if_cancel_requested
from .tool_tasks import report_tool_progress


def run_reporting_process(command, *, timeout=None, input=None, capture_output=False, check=False, **options):
    if capture_output:
        options.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if input is not None:
        options["stdin"] = subprocess.PIPE
    if os.name != "nt":
        options["start_new_session"] = True
    proc = subprocess.Popen(command, **options)
    proc._agentpark_process_group = os.name != "nt"
    started = time.monotonic()
    report_at = started + timeout if timeout and timeout > 0 else None
    pending_input = input
    try:
        while True:
            raise_if_cancel_requested(current_tool_call_cancel_source())
            try:
                stdout, stderr = proc.communicate(input=pending_input, timeout=.05)
                result = subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
                if check:
                    result.check_returncode()
                return result
            except subprocess.TimeoutExpired as exc:
                pending_input = None
                now = time.monotonic()
                due = report_at is not None and now >= report_at
                def preview(value):
                    return value[-2000:].decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")[-2000:]
                report_tool_progress({"pid": proc.pid, "elapsed_seconds": round(now - started, 3),
                                      "stdout_tail": preview(exc.stdout), "stderr_tail": preview(exc.stderr)}, request_report=due)
                if due:
                    report_at = None
    finally:
        if proc.poll() is None:
            terminate_process(proc)
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            if pipe is not None:
                pipe.close()
