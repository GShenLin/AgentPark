from __future__ import annotations

# Owns Claude Agent SDK sessions for node executions.
import asyncio
import atexit
import json
import os
import shutil
import threading
import uuid
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Coroutine

from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk import ClaudeSDKClient
from claude_agent_sdk import ResultMessage
from claude_agent_sdk import get_session_info
from claude_agent_sdk import get_session_messages
from claude_agent_sdk import list_sessions

from src.runtime_cancellation import CancellationRequested
from src.runtime_cancellation import is_cancel_requested

from .contracts import ClaudeSessionSpec
from .provider_gateway import ClaudeGatewayLease
from .provider_gateway import ClaudeProviderGateway
from .session_state import read_selected_session_id
from .session_state import write_selected_session_id


MessageHandler = Callable[[object], None]
ClientFactory = Callable[[ClaudeAgentOptions], ClaudeSDKClient]


@dataclass
class _ManagedSession:
    signature: str
    client: ClaudeSDKClient
    lease: ClaudeGatewayLease
    session_id: str
    turn_lock: threading.Lock


class _AsyncRuntime:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run,
            name="claude-agent-sdk-runtime",
            daemon=True,
        )
        self.thread.start()

    def call(self, coroutine: Coroutine[Any, Any, Any]) -> Any:
        future: Future[Any] = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        return future.result()

    def close(self) -> None:
        if not self.loop.is_running():
            return
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        if not self.thread.is_alive():
            self.loop.close()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()


class ClaudeSessionManager:
    _instance: "ClaudeSessionManager | None" = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        *,
        gateway: ClaudeProviderGateway | None = None,
        client_factory: ClientFactory = ClaudeSDKClient,
    ) -> None:
        self._gateway = gateway or ClaudeProviderGateway.instance()
        self._client_factory = client_factory
        self._runtime = _AsyncRuntime()
        self._lock = threading.RLock()
        self._sessions: dict[str, _ManagedSession] = {}

    @classmethod
    def instance(cls) -> "ClaudeSessionManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
                atexit.register(cls._instance.close_all)
            return cls._instance

    def run_turn(
        self,
        spec: ClaudeSessionSpec,
        text: str,
        *,
        event_handler: MessageHandler | None = None,
        gateway_observer: Callable[[dict[str, Any]], None] | None = None,
        cancel_source: object = None,
    ) -> str:
        normalized_text = str(text or "").strip()
        if not normalized_text:
            raise ValueError("Claude turn input is required.")
        with self._lock:
            session = self._session_for(spec)
            session.turn_lock.acquire()
        try:
            with self._gateway.observe_requests(session.lease.token, gateway_observer):
                result = self._runtime.call(
                    self._run_turn(
                        session,
                        normalized_text,
                        event_handler=event_handler,
                        cancel_source=cancel_source,
                    )
                )
            write_selected_session_id(spec.state_path, session.session_id)
            return result
        finally:
            session.turn_lock.release()

    def close_session(self, session_key: str) -> None:
        with self._lock:
            session = self._sessions.pop(str(session_key or ""), None)
        if session is not None:
            with session.turn_lock:
                self._close_session_resources(session)

    def list_sessions(self, cwd: str) -> list[Any]:
        return list_sessions(directory=os.path.abspath(cwd))

    def read_session(self, cwd: str, session_id: str) -> list[Any]:
        normalized = str(session_id or "").strip()
        if not normalized:
            raise ValueError("Claude session_id is required.")
        return get_session_messages(normalized, directory=os.path.abspath(cwd))

    def get_session_info(self, cwd: str, session_id: str) -> Any:
        normalized = str(session_id or "").strip()
        if not normalized:
            raise ValueError("Claude session_id is required.")
        return get_session_info(normalized, directory=os.path.abspath(cwd))

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            with session.turn_lock:
                self._close_session_resources(session)
        self._runtime.close()

    def _session_for(self, spec: ClaudeSessionSpec) -> _ManagedSession:
        self._validate_spec(spec)
        signature = spec.signature()
        current = self._sessions.get(spec.session_key)
        if current is not None and current.signature == signature:
            return current
        if current is not None:
            with current.turn_lock:
                self._close_session_resources(current)
            self._sessions.pop(spec.session_key, None)
        session = self._create_session(spec, signature)
        self._sessions[spec.session_key] = session
        return session

    def _create_session(self, spec: ClaudeSessionSpec, signature: str) -> _ManagedSession:
        lease = self._gateway.register(
            spec.provider_id,
            reasoning_effort=spec.reasoning_effort,
            model=spec.model,
        )
        selected_session_id = read_selected_session_id(spec.state_path)
        session_id = selected_session_id or str(uuid.uuid4())
        client: ClaudeSDKClient | None = None
        try:
            options = _agent_options(spec, lease, session_id, bool(selected_session_id))
            client = self._client_factory(options)
            self._runtime.call(client.connect())
            return _ManagedSession(
                signature=signature,
                client=client,
                lease=lease,
                session_id=session_id,
                turn_lock=threading.Lock(),
            )
        except Exception:
            if client is not None:
                try:
                    self._runtime.call(client.disconnect())
                except Exception:
                    pass
            self._gateway.release(lease.token)
            raise

    async def _run_turn(
        self,
        session: _ManagedSession,
        text: str,
        *,
        event_handler: MessageHandler | None,
        cancel_source: object,
    ) -> str:
        cancelled = asyncio.Event()

        async def watch_cancel() -> None:
            while True:
                if is_cancel_requested(cancel_source):
                    cancelled.set()
                    await session.client.interrupt()
                    return
                await asyncio.sleep(0.05)

        watcher = asyncio.create_task(watch_cancel()) if cancel_source is not None else None
        result_message: ResultMessage | None = None
        try:
            await session.client.query(text)
            async for message in session.client.receive_response():
                if callable(event_handler):
                    event_handler(message)
                if isinstance(message, ResultMessage):
                    result_message = message
                    if message.session_id:
                        session.session_id = message.session_id
        finally:
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
        if cancelled.is_set():
            raise CancellationRequested("Operation cancelled.")
        if result_message is None:
            raise RuntimeError("Claude Agent SDK ended without a ResultMessage.")
        if result_message.is_error:
            details = list(result_message.errors or [])
            if result_message.result:
                details.append(result_message.result)
            raise RuntimeError("\n".join(details) or f"Claude turn failed: {result_message.subtype}")
        return str(result_message.result or "")

    def _close_session_resources(self, session: _ManagedSession) -> None:
        try:
            self._runtime.call(session.client.disconnect())
        finally:
            self._gateway.release(session.lease.token)

    @staticmethod
    def _validate_spec(spec: ClaudeSessionSpec) -> None:
        for field_name in (
            "session_key",
            "provider_id",
            "model",
            "cwd",
            "permission_mode",
            "state_path",
        ):
            if not str(getattr(spec, field_name) or "").strip():
                raise ValueError(f"Claude session {field_name} is required.")
        if not os.path.isdir(spec.cwd):
            raise ValueError(f"Claude working directory does not exist: {spec.cwd}")


def _agent_options(
    spec: ClaudeSessionSpec,
    lease: ClaudeGatewayLease,
    session_id: str,
    resume: bool,
) -> ClaudeAgentOptions:
    env = {
        "ANTHROPIC_BASE_URL": lease.base_url,
        "ANTHROPIC_API_KEY": lease.token,
        "ANTHROPIC_AUTH_TOKEN": lease.token,
        "ANTHROPIC_CUSTOM_MODEL_OPTION": spec.model,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_TELEMETRY": "1",
    }
    cli_path = _resolve_cli_path(spec.command)
    settings = json.dumps({"env": env}, ensure_ascii=False, separators=(",", ":"))
    system_prompt: object = {
        "type": "preset",
        "preset": "claude_code",
        "append": spec.instruction,
    }
    return ClaudeAgentOptions(
        system_prompt=system_prompt,  # type: ignore[arg-type]
        permission_mode=spec.permission_mode,  # type: ignore[arg-type]
        resume=session_id if resume else None,
        session_id=None if resume else session_id,
        model=spec.model,
        cwd=Path(spec.cwd),
        cli_path=Path(cli_path),
        settings=settings,
        setting_sources=["user", "project", "local"],
        env=env,
        include_partial_messages=True,
        effort=spec.reasoning_effort or None,  # type: ignore[arg-type]
    )


def _resolve_cli_path(command: str) -> str:
    value = str(command or "").strip()
    resolved = shutil.which(value or "claude")
    if not resolved:
        raise FileNotFoundError(f"Claude executable was not found: {value or 'claude'}")
    path = os.path.abspath(resolved)
    if path.casefold().endswith((".cmd", ".ps1")):
        executable = os.path.join(
            os.path.dirname(path),
            "node_modules",
            "@anthropic-ai",
            "claude-code",
            "bin",
            "claude.exe",
        )
        if os.path.isfile(executable):
            path = executable
    if not path.casefold().endswith(".exe") or not os.path.isfile(path):
        raise ValueError(
            "Claude Agent SDK on Windows requires the native claude.exe; "
            f"resolved {value or 'claude'!r} to {path!r}."
        )
    return path


__all__ = ["ClaudeSessionManager", "ClaudeSessionSpec"]
