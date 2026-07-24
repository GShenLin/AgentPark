from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any

from src.runtime_cancellation import CancellationRequested
from src.runtime_cancellation import raise_if_cancel_requested


class CodexAppServerError(RuntimeError):
    pass


class CodexAppServerClient:
    def __init__(self, command: str = "codex") -> None:
        self.command = _resolve_command(command)
        self._write_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._next_id = 1
        self._pending: dict[int, queue.Queue] = {}
        self._notifications: queue.Queue = queue.Queue()
        self._stderr_lines: list[str] = []
        self._closed = False
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            self._proc = subprocess.Popen(
                _app_server_command(self.command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise CodexAppServerError(
                f"Failed to launch Codex app-server with {self.command!r}: {exc}"
            ) from exc
        self._stdout_thread = threading.Thread(target=self._read_stdout, name="codex-app-server-stdout", daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, name="codex-app-server-stderr", daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "agentpark",
                    "title": "AgentPark Codex Node",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
            timeout=20.0,
        )
        self.notify("initialized", {})

    def request(self, method: str, params: dict[str, Any], *, timeout: float = 30.0) -> dict[str, Any]:
        if self._closed:
            raise CodexAppServerError("Codex app-server client is closed.")
        with self._request_lock:
            request_id = self._next_id
            self._next_id += 1
            response_queue: queue.Queue = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
        try:
            self._send({"method": method, "id": request_id, "params": params})
            try:
                response = response_queue.get(timeout=max(0.1, timeout))
            except queue.Empty as exc:
                raise CodexAppServerError(
                    f"Codex app-server request {method!r} timed out. {self._stderr_summary()}"
                ) from exc
        finally:
            with self._request_lock:
                self._pending.pop(request_id, None)
        if not isinstance(response, dict):
            raise CodexAppServerError(f"Codex app-server returned an invalid response for {method!r}.")
        if "error" in response:
            raise CodexAppServerError(f"Codex app-server {method!r} failed: {response['error']}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise CodexAppServerError(f"Codex app-server {method!r} response has no result object.")
        return result

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def start_thread(
        self,
        *,
        model: str,
        model_provider: str,
        provider_config: dict[str, Any],
        cwd: str,
        sandbox: str,
        base_instructions: str = "",
        developer_instructions: str = "",
        reasoning_effort: str = "",
        web_search: str = "disabled",
        resume_thread_id: str = "",
    ) -> str:
        config_overrides: dict[str, Any] = {f"model_providers.{model_provider}": provider_config}
        if reasoning_effort:
            config_overrides["model_reasoning_effort"] = reasoning_effort
        config_overrides["web_search"] = web_search
        params: dict[str, Any] = {
            "model": model,
            "modelProvider": model_provider,
            "cwd": cwd,
            "approvalPolicy": "never",
            "sandbox": sandbox,
            "config": config_overrides,
        }
        if not resume_thread_id:
            params["experimentalRawEvents"] = True
        if base_instructions:
            params["baseInstructions"] = base_instructions
        if developer_instructions:
            params["developerInstructions"] = developer_instructions
        if resume_thread_id:
            params["threadId"] = resume_thread_id
            result = self.request("thread/resume", params, timeout=30.0)
        else:
            result = self.request("thread/start", params, timeout=30.0)
        thread = result.get("thread")
        thread_id = str(thread.get("id") or "").strip() if isinstance(thread, dict) else ""
        if not thread_id:
            raise CodexAppServerError("Codex app-server did not return a thread id.")
        return thread_id

    def list_threads(self) -> list[dict[str, Any]]:
        threads: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, Any] = {
                "limit": 100,
                "sortKey": "updated_at",
                "sortDirection": "desc",
                "modelProviders": [],
            }
            if cursor:
                params["cursor"] = cursor
            result = self.request("thread/list", params, timeout=30.0)
            data = result.get("data")
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise CodexAppServerError("Codex app-server thread/list returned invalid thread data.")
            threads.extend(dict(item) for item in data)
            next_cursor = str(result.get("nextCursor") or "").strip()
            if not next_cursor:
                return threads
            if next_cursor in seen_cursors:
                raise CodexAppServerError("Codex app-server thread/list returned a repeated pagination cursor.")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    def read_thread(self, thread_id: str) -> dict[str, Any]:
        selected_thread_id = str(thread_id or "").strip()
        if not selected_thread_id:
            raise ValueError("Codex thread id is required.")
        result = self.request(
            "thread/read",
            {"threadId": selected_thread_id, "includeTurns": True},
            timeout=30.0,
        )
        thread = result.get("thread")
        if not isinstance(thread, dict):
            raise CodexAppServerError("Codex app-server thread/read returned no thread.")
        returned_thread_id = str(thread.get("id") or "").strip()
        if returned_thread_id != selected_thread_id:
            raise CodexAppServerError(
                f"Codex app-server thread/read returned thread {returned_thread_id!r}, expected {selected_thread_id!r}."
            )
        return dict(thread)

    def run_turn(
        self,
        thread_id: str,
        text: str,
        *,
        event_handler: Callable[[dict[str, Any]], None] | None = None,
        cancel_source: object = None,
    ) -> str:
        result = self.request(
            "turn/start",
            {"threadId": thread_id, "input": [{"type": "text", "text": text}]},
            timeout=30.0,
        )
        turn = result.get("turn")
        turn_id = str(turn.get("id") or "").strip() if isinstance(turn, dict) else ""
        if not turn_id:
            raise CodexAppServerError("Codex app-server did not return a turn id.")
        final_text = ""
        interrupted = False
        while True:
            try:
                raise_if_cancel_requested(cancel_source)
            except CancellationRequested:
                if not interrupted:
                    self.request(
                        "turn/interrupt",
                        {"threadId": thread_id, "turnId": turn_id},
                        timeout=10.0,
                    )
                    interrupted = True
            self._raise_if_exited()
            try:
                event = self._notifications.get(timeout=0.1)
            except queue.Empty:
                continue
            if not isinstance(event, dict):
                continue
            params = event.get("params")
            if isinstance(params, dict):
                event_thread_id, event_turn_id = _notification_identity(params)
                if event_thread_id and event_thread_id != thread_id:
                    continue
                if event_turn_id and event_turn_id != turn_id:
                    continue
            if callable(event_handler):
                event_handler(event)
            method = str(event.get("method") or "")
            if method == "item/agentMessage/delta" and isinstance(params, dict):
                final_text += str(params.get("delta") or "")
            elif method == "item/completed" and isinstance(params, dict):
                item = params.get("item")
                if isinstance(item, dict) and str(item.get("type") or "") == "agentMessage":
                    final_text = str(item.get("text") or final_text)
            elif method == "turn/completed" and isinstance(params, dict):
                completed_turn = params.get("turn")
                status = str(completed_turn.get("status") or "") if isinstance(completed_turn, dict) else ""
                if status == "failed":
                    error = completed_turn.get("error") if isinstance(completed_turn, dict) else None
                    raise CodexAppServerError(f"Codex turn failed: {error}")
                if interrupted or status == "interrupted":
                    raise CancellationRequested("Codex turn cancelled.")
                if status != "completed":
                    raise CodexAppServerError(f"Codex turn completed with unsupported status: {status or '<empty>'}")
                return final_text

    def is_alive(self) -> bool:
        return not self._closed and self._proc.poll() is None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        proc = self._proc
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        for pending in list(self._pending.values()):
            try:
                pending.put_nowait({"error": "Codex app-server closed."})
            except queue.Full:
                pass

    def _read_stdout(self) -> None:
        stdout = self._proc.stdout
        if stdout is None:
            return
        for line in stdout:
            text = line.strip()
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError:
                self._append_stderr(f"invalid app-server JSON: {text}")
                continue
            if not isinstance(message, dict):
                continue
            request_id = message.get("id")
            if isinstance(request_id, int) and ("result" in message or "error" in message):
                with self._request_lock:
                    pending = self._pending.get(request_id)
                if pending is not None:
                    try:
                        pending.put_nowait(message)
                    except queue.Full:
                        pass
                continue
            if isinstance(request_id, int) and isinstance(message.get("method"), str):
                self._handle_server_request(message)
                continue
            if isinstance(message.get("method"), str):
                self._notifications.put(message)

    def _read_stderr(self) -> None:
        stderr = self._proc.stderr
        if stderr is None:
            return
        for line in stderr:
            self._append_stderr(line.rstrip())

    def _handle_server_request(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        method = str(message.get("method") or "")
        self._notifications.put(
            {
                "method": "agentpark/serverRequestDeclined",
                "params": {"requestMethod": method, "request": message.get("params")},
            }
        )
        if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
            self._send({"id": request_id, "result": {"decision": "decline"}})
            return
        if method == "item/permissions/requestApproval":
            self._send({"id": request_id, "result": {"permissions": {}, "scope": "turn"}})
            return
        if method == "mcpServer/elicitation/request":
            self._send({"id": request_id, "result": {"action": "decline", "content": None, "_meta": None}})
            return
        self._send(
            {
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": f"AgentPark Codex Node does not implement server request {method!r}.",
                },
            }
        )

    def _send(self, payload: dict[str, Any]) -> None:
        stdin = self._proc.stdin
        if stdin is None or self._proc.poll() is not None:
            raise CodexAppServerError(f"Codex app-server is not running. {self._stderr_summary()}")
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            stdin.write(line + "\n")
            stdin.flush()

    def _raise_if_exited(self) -> None:
        code = self._proc.poll()
        if code is not None:
            raise CodexAppServerError(f"Codex app-server exited with code {code}. {self._stderr_summary()}")

    def _append_stderr(self, line: str) -> None:
        if not line:
            return
        self._stderr_lines.append(line)
        if len(self._stderr_lines) > 40:
            del self._stderr_lines[:-40]

    def _stderr_summary(self) -> str:
        text = " | ".join(self._stderr_lines[-5:])
        return f"stderr: {text}" if text else "stderr is empty."


def _resolve_command(command: str) -> str:
    raw = str(command or "codex").strip() or "codex"
    expanded = os.path.abspath(os.path.expanduser(raw)) if any(separator in raw for separator in ("/", "\\")) else raw
    if os.path.isfile(expanded):
        if os.name == "nt" and _is_windows_apps_path(expanded):
            raise ValueError(
                "Codex command resolves to a WindowsApps package executable that cannot be launched "
                "by AgentPark. Configure a standalone Codex CLI path instead."
            )
        return expanded
    if any(separator in raw for separator in ("/", "\\")):
        raise ValueError(f"Codex command does not exist: {expanded}")
    if os.name == "nt":
        shim = shutil.which(f"{raw}.cmd")
        if shim and not _is_windows_apps_path(shim):
            return shim
        bundled = _bundled_windows_codex_command(raw)
        if bundled:
            return bundled
        candidates = [f"{raw}.exe", raw]
    else:
        candidates = [raw]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved and not _is_windows_apps_path(resolved):
            return resolved
    if os.name == "nt":
        raise ValueError(
            "Cannot find a launchable Codex command. Install the Codex CLI or configure codex_command "
            "with a standalone executable path."
        )
    raise ValueError(f"Cannot find Codex command on PATH: {raw}")


def _bundled_windows_codex_command(raw: str) -> str:
    if raw.casefold() not in {"codex", "codex.exe"}:
        return ""
    codex_home = os.path.join(os.path.expanduser("~"), ".codex")
    candidates = (
        os.path.join(codex_home, ".sandbox-bin", "codex.exe"),
        os.path.join(codex_home, "plugins", ".plugin-appserver", "codex.exe"),
    )
    return next((candidate for candidate in candidates if os.path.isfile(candidate)), "")


def _is_windows_apps_path(path: str) -> bool:
    normalized = os.path.normcase(os.path.abspath(os.path.expanduser(str(path or ""))))
    return "\\windowsapps\\" in normalized


def _app_server_command(command: str) -> list[str]:
    if os.name == "nt" and os.path.splitext(command)[1].lower() in {".cmd", ".bat"}:
        command_line = subprocess.list2cmdline([command, "app-server", "--listen", "stdio://"])
        return [os.environ.get("COMSPEC") or "cmd.exe", "/d", "/s", "/c", command_line]
    return [command, "app-server", "--listen", "stdio://"]


def _notification_identity(params: dict[str, Any]) -> tuple[str, str]:
    thread_id = str(params.get("threadId") or "")
    turn_id = str(params.get("turnId") or "")
    turn = params.get("turn")
    if isinstance(turn, dict):
        turn_id = turn_id or str(turn.get("id") or "")
        thread_id = thread_id or str(turn.get("threadId") or "")
    return thread_id, turn_id


__all__ = ["CodexAppServerClient", "CodexAppServerError"]
