"""Own the app-server process tree independently of its JSON-RPC protocol."""
from __future__ import annotations

import os
import signal
import subprocess

from .executable import CodexExecutable


class ServerProcess:
    def __init__(self, executable: CodexExecutable) -> None:
        self.job = None
        self.process = None
        if os.name == "nt":
            from src.harness.windows_job import WindowsJob
            self.job = WindowsJob()
        try:
            self.process = subprocess.Popen(
                [executable.path, "app-server", "--listen", "stdio://"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="strict", bufsize=1,
                env=executable.environment(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            if self.job:
                self.job.assign(int(self.process._handle))
        except BaseException:
            if self.process is not None:
                self.process.kill()
                self.process.wait(timeout=10)
                for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
                    if pipe is not None:
                        pipe.close()
            if self.job:
                self.job.close()
            raise

    def close(self) -> None:
        if self.process.stdin is not None and not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except BrokenPipeError:
                pass  # The server already closed its input pipe.
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass  # Escalate to the owned process tree below.
        if self.job:
            self.job.close()
        else:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # This process group has already exited.
        self.process.wait(timeout=10)
