import os
import shlex
import subprocess
import time

from nodes.base_node import BaseNode
from src.message_protocol import build_text_envelope, envelope_text
from src.runtime_cancellation import CancellationRequested, raise_if_cancel_requested
from src.value_parsing import parse_bool_value, parse_int_value


class Node(BaseNode):
    name = "ConsoleCommand"
    description = "执行命令行命令，并分别输出 stdout、stderr、returncode"
    input_capabilities = ["text"]
    output_capabilities = ["text"]
    config_defaults = {
        "Command": "",
        "TimeoutSeconds": 15,
        "Shell": True,
    }
    config_schema = {
        "Command": {
            "type": "text",
            "label": "命令(可空，留空则使用输入内容)",
            "description": "要执行的命令。为空时会把节点输入文本作为命令执行。",
        },
        "TimeoutSeconds": {
            "type": "number",
            "label": "超时秒数",
            "min": 1,
            "max": 3600,
            "step": 1,
            "description": "命令最长执行时间，超时后会终止进程。",
        },
        "Shell": {
            "type": "boolean",
            "label": "使用 Shell 执行",
            "description": "启用时等价于 subprocess.run(..., shell=True)，支持管道、重定向等 shell 语法。",
        },
    }

    def getInputNum(self, context: dict | None = None) -> int:
        return 1

    def getOutputNum(self, context: dict | None = None) -> int:
        # 0: stdout, 1: stderr, 2: returncode
        return 3

    @staticmethod
    def _resolve_cwd(context: dict | None = None) -> str | None:
        ctx = context if isinstance(context, dict) else {}
        cwd = str(ctx.get("working_path") or ctx.get("WorkingDirectory") or "").strip()
        if not cwd:
            return None
        cwd = os.path.abspath(os.path.expanduser(cwd))
        if not os.path.isdir(cwd):
            raise ValueError(f"Working directory does not exist: {cwd}")
        return cwd

    @staticmethod
    def _build_args(command: str, shell: bool) -> str | list[str]:
        if shell:
            return command
        return shlex.split(command, posix=(os.name != "nt"))

    def _make_result(self, stdout: str, stderr: str, returncode: int) -> dict:
        stdout_env = build_text_envelope(stdout, role="assistant")
        stderr_env = build_text_envelope(stderr, role="assistant")
        returncode_env = build_text_envelope(str(returncode), role="assistant")
        display = (
            f"returncode: {returncode}\n"
            f"--- stdout ---\n{stdout}\n"
            f"--- stderr ---\n{stderr}"
        )
        return {
            "display": display,
            "routes": [
                {"output_index": 0, "payload": stdout_env},
                {"output_index": 1, "payload": stderr_env},
                {"output_index": 2, "payload": returncode_env},
            ],
        }

    @staticmethod
    def _terminate_process(proc: subprocess.Popen | None) -> None:
        if proc is None or proc.poll() is not None:
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

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context if isinstance(context, dict) else {}
        configured_command = str(ctx.get("Command") or "").strip()
        input_command = envelope_text(message).strip()
        command = configured_command or input_command
        if not command:
            raise ValueError("Command is required. Set Command config or pass command text as input.")

        timeout = parse_int_value(ctx.get("TimeoutSeconds"), default=15, minimum=1, maximum=3600)
        shell = parse_bool_value(ctx.get("Shell"), default=True)
        cwd = self._resolve_cwd(ctx)
        cancel_source = ctx.get("cancel_event") or ctx.get("cancel_check")

        try:
            proc = subprocess.Popen(
                self._build_args(command, shell),
                shell=shell,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                try:
                    raise_if_cancel_requested(cancel_source)
                except CancellationRequested:
                    self._terminate_process(proc)
                    raise
                if time.monotonic() >= deadline:
                    self._terminate_process(proc)
                    stdout, stderr = proc.communicate(timeout=0.2)
                    stderr = ((stderr or "") + ("\n" if stderr else "") + f"Command timed out after {timeout} seconds.").strip()
                    return self._make_result(stdout or "", stderr, -1)
                time.sleep(0.05)

            stdout, stderr = proc.communicate(timeout=0.2)
            returncode = int(proc.returncode)
        except CancellationRequested as exc:
            stdout = ""
            stderr = str(exc)
            returncode = -1
        except Exception as exc:
            stdout = ""
            stderr = f"{type(exc).__name__}: {exc}"
            returncode = -1

        return self._make_result(stdout, stderr, returncode)
