import locale
import os
import shlex
import signal
import subprocess
import sys
import time
import uuid
from threading import Lock, Thread
from queue import Queue, Empty

from nodes.base_node import BaseNode
from src.console_interactive_sessions import register_console_interactive_proc
from src.console_interactive_sessions import send_console_interactive_input
from src.console_interactive_sessions import unregister_console_interactive_proc
from src.message_protocol import build_text_envelope, envelope_text
from src.node_stream_protocol import build_node_message_delta, build_node_message_done
from src.runtime_cancellation import CancellationRequested, raise_if_cancel_requested
from src.value_parsing import parse_bool_value, parse_int_value


class Node(BaseNode):
    name = "ConsoleCommand"
    description = "执行命令行命令，并分别输出 stdout、stderr、returncode。运行期间实时显示 stdout/stderr。"
    input_capabilities = ["text"]
    output_capabilities = ["text"]
    config_defaults = {
        "Command": "",
        "TimeoutSeconds": 15,
        "Shell": True,
        "Encoding": "auto",
        "CloseStdin": False,
        "Interactive": True,
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
            "min": 0,
            "max": 3600,
            "step": 1,
            "description": "命令最长执行时间，超时后会终止进程；设置为 0 表示不限制时间。",
        },
        "Shell": {
            "type": "boolean",
            "label": "使用 Shell 执行",
            "description": "启用时等价于 subprocess.Popen(..., shell=True)，支持管道、重定向等 shell 语法。",
        },
        "Encoding": {
            "type": "text",
            "label": "输出编码",
            "description": "命令输出的文本编码。auto 自动使用系统默认编码；中文 Windows 通常是 gbk/cp936，也可手动填写 utf-8。",
        },
        "CloseStdin": {
            "type": "boolean",
            "label": "关闭标准输入",
            "description": "启用后将 stdin 重定向到空设备，避免命令等待 pause、set /p、input() 之类的用户输入而永久卡住。",
        },
        "Interactive": {
            "type": "boolean",
            "label": "启用交互式输入",
            "description": "启用后命令运行时可在前端面板输入内容、发送回车/Ctrl+C/Ctrl+D，支持YES/NO确认、密码输入等场景。",
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

    @staticmethod
    def _resolve_encoding(encoding_cfg: str) -> str:
        encoding = str(encoding_cfg or "auto").strip() or "auto"
        if encoding.lower() != "auto":
            return encoding
        # Windows下控制台程序默认输出用OEM编码，中文系统通常是cp936/gbk，优先取系统实际控制台编码
        if os.name == "nt":
            try:
                import ctypes
                oem_cp = ctypes.windll.kernel32.GetOEMCP()
                if oem_cp:
                    return f"cp{oem_cp}"
            except Exception:
                pass
        return (
            locale.getpreferredencoding(False)
            or "utf-8"
        )

    @staticmethod
    def _decode_bytes(data: bytes, encoding: str) -> str:
        """优先用指定编码解码，失败自动回退到utf-8/gbk，最大程度避免乱码"""
        if not data:
            return ""
        # 候选编码顺序：指定编码 -> utf-8 -> gbk -> mbcs
        candidates = []
        for enc in [encoding, "utf-8", "gbk", "mbcs"]:
            if enc and enc not in candidates:
                candidates.append(enc)
        best_text = ""
        best_errors = float("inf")
        for enc in candidates:
            try:
                text = data.decode(enc, errors="strict")
                # 没有错误直接用
                return text
            except UnicodeDecodeError:
                # 计算替换字符数量，选最少的
                text = data.decode(enc, errors="replace")
                err_count = text.count("\ufffd")
                if err_count < best_errors:
                    best_errors = err_count
                    best_text = text
        return best_text

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

    @staticmethod
    def send_interactive_input(session_id: str, text: str, *, send_eof: bool = False, send_ctrl_c: bool = False, append_newline: bool = False) -> bool:
        """给运行中的交互式命令发送输入（线程安全，通过writer线程写stdin）"""
        return send_console_interactive_input(
            session_id,
            text,
            send_eof=send_eof,
            send_ctrl_c=send_ctrl_c,
            append_newline=append_newline,
        )

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context if isinstance(context, dict) else {}
        configured_command = str(ctx.get("Command") or "").strip()
        input_command = envelope_text(message).strip()
        command = configured_command or input_command
        if not command:
            raise ValueError("Command is required. Set Command config or pass command text as input.")

        timeout = parse_int_value(ctx.get("TimeoutSeconds"), default=15, minimum=0, maximum=3600)
        shell = parse_bool_value(ctx.get("Shell"), default=True)
        encoding = self._resolve_encoding(str(ctx.get("Encoding") or "auto"))
        close_stdin = parse_bool_value(ctx.get("CloseStdin"), default=True)
        interactive = parse_bool_value(ctx.get("Interactive"), default=True)
        # Interactive 显式开启时强制打开 stdin；否则尊重 CloseStdin 配置
        if interactive:
            close_stdin = False
        cwd = self._resolve_cwd(ctx)
        cancel_source = ctx.get("cancel_event") or ctx.get("cancel_check")
        stream_callback = ctx.get("stream_callback") if callable(ctx.get("stream_callback")) else None

        proc: subprocess.Popen | None = None
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        lock = Lock()
        input_queue: Queue = Queue() if not close_stdin else None
        session_id = str(uuid.uuid4()) if interactive and not close_stdin else ""
        live_text = f"$ {command}\n"
        if cwd:
            live_text += f"[cwd] {cwd}\n"
        live_text += "\n"

        def emit_delta(delta: str) -> None:
            nonlocal live_text
            if not stream_callback or not delta:
                return
            preview = live_text.rstrip("\n") + "\n\n[running...]"
            try:
                stream_callback(build_node_message_delta(delta, preview))
            except Exception:
                pass

        def publish_event(event_type: str, event_data: dict) -> None:
            if not stream_callback:
                return
            try:
                # 复用delta通道发送控制事件
                preview = live_text.rstrip("\n") + "\n\n[running...]"
                payload = build_node_message_delta("", preview, force=True)
                payload["event"] = {"type": event_type, **event_data}
                stream_callback(payload)
            except Exception:
                pass

        def stdin_writer_thread() -> None:
            """专门写stdin的线程，从队列取输入"""
            nonlocal proc
            if not proc or not proc.stdin or not input_queue:
                return
            try:
                publish_event("stdin_ready", {"session_id": session_id})
                while proc.poll() is None:
                    try:
                        item = input_queue.get(timeout=0.2)
                    except Empty:
                        continue
                    if item is None:
                        break
                    text = str(item.get("text") or "")
                    send_eof = bool(item.get("send_eof"))
                    send_ctrl_c = bool(item.get("send_ctrl_c"))
                    try:
                        if send_ctrl_c:
                            if os.name == "nt":
                                # 新建进程组后 CTRL_C_EVENT 可能被禁用，CTRL_BREAK_EVENT 更可靠
                                try:
                                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                                except Exception:
                                    proc.terminate()
                            else:
                                proc.stdin.write(b"\x03")
                        if text:
                            proc.stdin.write(text.encode(encoding, errors="replace"))
                        if send_eof:
                            if os.name != "nt":
                                proc.stdin.write(b"\x04")
                            proc.stdin.close()
                            break
                        else:
                            proc.stdin.flush()
                    except Exception:
                        break
            except Exception:
                pass

        def append_stream(pipe_name: str, stream, chunks: list[str]) -> None:
            nonlocal live_text
            prefix = "[stderr] " if pipe_name == "stderr" else ""
            try:
                for raw_line in iter(stream.readline, b""):
                    if not raw_line:
                        break
                    line = self._decode_bytes(raw_line, encoding)
                    chunks.append(line)
                    if lock.acquire(timeout=0.2):
                        try:
                            piece = f"{prefix}{line}"
                            live_text += piece
                            emit_delta(piece)
                        finally:
                            lock.release()
            except Exception:
                pass
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        returncode = -1
        timed_out = False
        cancelled = False
        stderr_extra = ""
        popen_kwargs = dict(
            shell=shell,
            cwd=cwd,
            stdin=subprocess.DEVNULL if close_stdin else subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            bufsize=1,
        )
        if os.name == "nt" and not close_stdin:
            # 新建进程组，避免向父进程自身发送 Ctrl+C
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        try:
            proc = subprocess.Popen(self._build_args(command, shell), **popen_kwargs)

            # 注册到活动进程表，供API发送输入
            if session_id and not close_stdin:
                register_console_interactive_proc(
                    session_id,
                    proc=proc,
                    encoding=encoding,
                    input_queue=input_queue,
                    graph_id=str(ctx.get("graph_id") or ""),
                    node_id=str(ctx.get("node_instance_id") or ctx.get("node_id") or ""),
                )

            stdout_thread = Thread(target=append_stream, args=("stdout", proc.stdout, stdout_chunks), daemon=True)
            stderr_thread = Thread(target=append_stream, args=("stderr", proc.stderr, stderr_chunks), daemon=True)
            stdin_thread = Thread(target=stdin_writer_thread, daemon=True) if input_queue else None
            stdout_thread.start()
            stderr_thread.start()
            if stdin_thread:
                stdin_thread.start()

            deadline = None if timeout == 0 else time.monotonic() + timeout
            while proc.poll() is None:
                try:
                    raise_if_cancel_requested(cancel_source)
                except CancellationRequested:
                    self._terminate_process(proc)
                    cancelled = True
                    stderr_extra = "Command cancelled."
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    self._terminate_process(proc)
                    timed_out = True
                    stderr_extra = f"Command timed out after {timeout} seconds."
                    break
                time.sleep(0.05)

            stdout_thread.join(timeout=1.0)
            stderr_thread.join(timeout=1.0)
            if stdin_thread:
                input_queue.put(None)
                stdin_thread.join(timeout=1.0)
            returncode = proc.returncode if proc.returncode is not None else -1
        except CancellationRequested as exc:
            returncode = -1
            cancelled = True
            stderr_extra = str(exc)
        except Exception as exc:
            returncode = -1
            stderr_extra = f"{type(exc).__name__}: {exc}"
        finally:
            # 注销活动进程
            if session_id:
                unregister_console_interactive_proc(session_id)
            self._terminate_process(proc)
            try:
                stdout_thread.join(timeout=0.5)
            except Exception:
                pass
            try:
                stderr_thread.join(timeout=0.5)
            except Exception:
                pass
            try:
                if stdin_thread:
                    stdin_thread.join(timeout=0.5)
            except Exception:
                pass
            publish_event("stdin_closed", {"session_id": session_id})

        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)
        if stderr_extra:
            stderr = ((stderr.rstrip("\n") + "\n") if stderr.strip() else stderr) + stderr_extra
        if timed_out or cancelled:
            returncode = -1

        result = self._make_result(stdout, stderr, returncode)
        if stream_callback:
            try:
                stream_callback(build_node_message_done(result["display"]))
            except Exception:
                pass
        return result
