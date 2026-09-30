"""One command's process, output and completion lifecycle; independent of tools."""

from pathlib import Path
import os
import subprocess
import tempfile
import threading
import time
import uuid

from functions.console_process_runtime import terminate_process
from functions.console_session_output import SessionOutput
from functions.console_shell import ConsoleLaunch
from src.runtime_cancellation import is_cancel_requested, raise_if_cancel_requested


class ConsoleSession:
    def __init__(self, command, cwd, timeout_seconds, cancel_source, child_process_policy="error"):
        raise_if_cancel_requested(cancel_source)
        self.session_id = uuid.uuid4().hex
        self.command, self.cwd = command, cwd
        self.started = time.monotonic()
        self.deadline = self.started + timeout_seconds if timeout_seconds else None
        self.cancel_source = cancel_source
        self.child_process_policy = child_process_policy
        self.terminated_children = 0
        self.condition = threading.Condition()
        self.stop_requested = threading.Event()
        self.done = threading.Event()
        self.status = "running"
        self.error = None
        self.returncode = None
        self.directory = tempfile.TemporaryDirectory(prefix="agentpark-session-")
        self.launch = None
        self.proc = None
        self.job = None
        self.outputs = []
        try:
            self.launch = ConsoleLaunch(command)
            if os.name == "nt":
                self.launch.options["creationflags"] |= 0x00000004  # CREATE_SUSPENDED until job assignment
            self.proc = subprocess.Popen(
                self.launch.argv, cwd=cwd, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, **self.launch.options,
            )
            self.proc._agentpark_process_group = bool(self.launch.options.get("start_new_session"))
            if os.name == "nt":
                from functions.console_windows_job import WindowsProcessJob
                self.job = WindowsProcessJob(self.proc)
            self.stdout = SessionOutput(Path(self.directory.name) / "stdout", self.proc.stdout, self.condition)
            self.outputs.append(self.stdout)
            self.stderr = SessionOutput(Path(self.directory.name) / "stderr", self.proc.stderr, self.condition)
            self.outputs.append(self.stderr)
            self.monitor = threading.Thread(target=self._monitor, daemon=True, name="console-session-monitor")
            self.monitor.start()
        except BaseException:
            if self.job is not None:
                self.job.close()
            if self.proc is not None:
                terminate_process(self.proc)
            for output in self.outputs:
                output.thread.join(timeout=6)
            if self.launch is not None:
                self.launch.close()
            self.directory.cleanup()
            raise

    def _monitor(self):
        outcome = "running"
        error = None
        try:
            while self.proc.poll() is None:
                if self.stop_requested.is_set() or is_cancel_requested(self.cancel_source):
                    outcome, error = "stopped", "Command cancelled; its process tree was terminated."
                elif self.deadline is not None and time.monotonic() >= self.deadline:
                    outcome, error = "timeout", "Command execution deadline exceeded."
                elif any(output.error for output in self.outputs):
                    outcome, error = "error", "Console output capture failed."
                if outcome != "running":
                    self._terminate()
                    self.proc.wait(timeout=5)
                    break
                self.stop_requested.wait(0.05)
            # Close ownership before draining: even a child whose parent exited stays in the job.
            if self.job is not None:
                if outcome == "running":
                    self.terminated_children = self.job.active_process_count()
                    if self.terminated_children and self.child_process_policy == "error":
                        outcome = "error"
                        error = ("Shell exited while child processes were still running; children were terminated. "
                                 "Run the command in the foreground. For Windows GUI executables, pipe to Out-Default "
                                 "to wait, or use Start-Process -Wait -PassThru and exit with its ExitCode. "
                                 "For intentionally remaining helpers, explicitly set child_process_policy=terminate.")
                self.job.close()
            else:
                terminate_process(self.proc)
            # Shell completion is not output completion: children may still own pipes.
            drain_deadline = time.monotonic() + 5
            for output in self.outputs:
                output.thread.join(timeout=max(0, drain_deadline - time.monotonic()))
            if any(output.thread.is_alive() for output in self.outputs):
                self._terminate()
                for output in self.outputs:
                    output.thread.join(timeout=2)
                if any(output.thread.is_alive() for output in self.outputs):
                    raise RuntimeError("Process exited but output pipes remain open; command must not detach children")
            output_errors = [output.error for output in self.outputs if output.error]
            if output_errors:
                outcome, error = "error", "; ".join(output_errors)
            if outcome == "running":
                outcome = "success" if self.proc.returncode == 0 else "error"
        except Exception as exc:
            outcome, error = "error", f"Process lifecycle failure: {type(exc).__name__}: {exc}"
        finally:
            try:
                if self.job is not None:
                    self.job.close()
                self.launch.close()
            except Exception as exc:
                outcome, error = "error", f"Command script cleanup failed: {exc}"
            with self.condition:
                self.status, self.error = outcome, error
                self.returncode = self.proc.poll()
                self.done.set()
                self.condition.notify_all()

    def _terminate(self):
        if self.job is not None:
            self.job.close()
        else:
            terminate_process(self.proc)

    def snapshot(self, cursor, max_chars):
        with self.condition:
            if cursor is None:
                cursor = {"session_id": self.session_id, "stdout": 0, "stderr": 0}
            if not isinstance(cursor, dict) or set(cursor) != {"session_id", "stdout", "stderr"}:
                raise ValueError("cursor must contain exactly session_id, stdout and stderr")
            if cursor["session_id"] != self.session_id:
                raise ValueError("Output cursor belongs to another session")
            stdout = self.stdout.read(cursor["stdout"], max_chars)
            stderr = self.stderr.read(cursor["stderr"], max_chars)
            next_cursor = {"session_id": self.session_id,
                           "stdout": cursor["stdout"] + len(stdout), "stderr": cursor["stderr"] + len(stderr)}
            result = {
                "session_id": self.session_id, "pid": self.proc.pid, "cwd": self.cwd,
                "status": self.status, "finished": self.done.is_set(), "returncode": self.returncode,
                "stdout": stdout, "stderr": stderr, "next_cursor": next_cursor,
                "has_more_output": next_cursor["stdout"] < self.stdout.length or next_cursor["stderr"] < self.stderr.length,
                "output_complete": self.stdout.finished and self.stderr.finished,
                "child_process_policy": self.child_process_policy,
                "terminated_children_on_shell_exit": self.terminated_children,
                "elapsed_seconds": round(time.monotonic() - self.started, 3),
            }
            if self.error:
                result["error"] = self.error
            return result

    def wait(self, wait_seconds, cancel_source):
        until = time.monotonic() + wait_seconds
        cancelled = False
        with self.condition:
            while not self.done.is_set():
                if is_cancel_requested(cancel_source):
                    self.stop_requested.set()
                    cancelled = True
                    break
                remaining = until - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(min(remaining, 0.05))
        if cancelled and not self.done.wait(20):
            raise RuntimeError("Cancelled session failed to stop")

    def close(self):
        self.stop_requested.set()
        if not self.done.wait(20):
            raise RuntimeError(f"Session {self.session_id} failed to stop during cleanup")
        if any(output.thread.is_alive() for output in self.outputs):
            raise RuntimeError(f"Session {self.session_id} still has live output readers")
        self.directory.cleanup()
