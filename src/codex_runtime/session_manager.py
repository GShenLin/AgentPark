from __future__ import annotations

import atexit
import hashlib
import json
import os
import threading
from dataclasses import dataclass
from typing import Callable

from .app_server_client import CodexAppServerClient
from .model_catalog import resolve_codex_runtime_model
from .provider_gateway import CodexProviderGateway
from .provider_gateway import GatewayLease
from .thread_state import read_selected_thread_id
from .thread_state import write_selected_thread_id


SESSION_SIGNATURE_VERSION = 1
MODEL_PROVIDER_ID = "agentpark"


@dataclass(frozen=True)
class CodexSessionSpec:
    session_key: str
    provider_id: str
    model: str
    command: str
    cwd: str
    sandbox: str
    state_path: str
    developer_instructions: str = ""
    base_instructions: str = ""
    reasoning_effort: str = ""
    web_search: str = "disabled"

    def signature(self) -> str:
        payload = {
            "version": SESSION_SIGNATURE_VERSION,
            "provider_id": self.provider_id,
            "model": self.model,
            "command": os.path.normcase(os.path.abspath(self.command))
            if any(separator in self.command for separator in ("/", "\\"))
            else self.command,
            "cwd": os.path.normcase(os.path.abspath(self.cwd)),
            "sandbox": self.sandbox,
            "developer_instructions": self.developer_instructions,
            "base_instructions": self.base_instructions,
            "reasoning_effort": self.reasoning_effort,
            "web_search": self.web_search,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass
class _ManagedSession:
    signature: str
    client: CodexAppServerClient
    lease: GatewayLease
    thread_id: str
    turn_lock: threading.Lock


class CodexSessionManager:
    _instance: "CodexSessionManager | None" = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        *,
        gateway: CodexProviderGateway | None = None,
        client_factory: Callable[[str], CodexAppServerClient] = CodexAppServerClient,
    ) -> None:
        self._gateway = gateway or CodexProviderGateway.instance()
        self._client_factory = client_factory
        self._lock = threading.RLock()
        self._sessions: dict[str, _ManagedSession] = {}
        self._catalog_clients: dict[str, CodexAppServerClient] = {}

    @classmethod
    def instance(cls) -> "CodexSessionManager":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
                atexit.register(cls._instance.close_all)
            return cls._instance

    def run_turn(
        self,
        spec: CodexSessionSpec,
        text: str,
        *,
        event_handler=None,
        cancel_source: object = None,
    ) -> str:
        with self._lock:
            session = self._session_for(spec)
            session.turn_lock.acquire()
        try:
            with self._gateway.observe_requests(session.lease.token, event_handler):
                return session.client.run_turn(
                    session.thread_id,
                    text,
                    event_handler=event_handler,
                    cancel_source=cancel_source,
                )
        finally:
            session.turn_lock.release()

    def close_session(self, session_key: str) -> None:
        with self._lock:
            session = self._sessions.pop(str(session_key or ""), None)
        if session is not None:
            with session.turn_lock:
                self._close_session_resources(session)

    def list_threads(self, command: str) -> list[dict]:
        return self._catalog_client(command).list_threads()

    def read_thread(self, command: str, thread_id: str) -> dict:
        return self._catalog_client(command).read_thread(thread_id)

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            catalog_clients = list(self._catalog_clients.values())
            self._catalog_clients.clear()
        for session in sessions:
            with session.turn_lock:
                self._close_session_resources(session)
        for client in catalog_clients:
            client.close()

    def _session_for(self, spec: CodexSessionSpec) -> _ManagedSession:
        self._validate_spec(spec)
        signature = spec.signature()
        with self._lock:
            current = self._sessions.get(spec.session_key)
            if current is not None and current.signature == signature and current.client.is_alive():
                return current
            if current is not None:
                with current.turn_lock:
                    self._close_session_resources(current)
                self._sessions.pop(spec.session_key, None)
            session = self._create_session(spec, signature)
            self._sessions[spec.session_key] = session
            return session

    def _create_session(self, spec: CodexSessionSpec, signature: str) -> _ManagedSession:
        lease = self._gateway.register(spec.provider_id)
        client: CodexAppServerClient | None = None
        try:
            client = self._client_factory(spec.command)
            model_selection = resolve_codex_runtime_model(
                client.request,
                spec.model,
                reasoning_effort=spec.reasoning_effort,
            )
            resume_thread_id = read_selected_thread_id(spec.state_path)
            thread_id = client.start_thread(
                model=model_selection.runtime_model,
                model_provider=MODEL_PROVIDER_ID,
                provider_config={
                    "name": f"AgentPark Provider {spec.provider_id}",
                    "base_url": lease.base_url,
                    "experimental_bearer_token": lease.token,
                    "wire_api": "responses",
                    "requires_openai_auth": False,
                    "supports_websockets": False,
                },
                cwd=spec.cwd,
                sandbox=spec.sandbox,
                base_instructions=spec.base_instructions,
                developer_instructions=spec.developer_instructions,
                reasoning_effort=spec.reasoning_effort,
                web_search=spec.web_search,
                resume_thread_id=resume_thread_id,
            )
            write_selected_thread_id(spec.state_path, thread_id)
            return _ManagedSession(
                signature=signature,
                client=client,
                lease=lease,
                thread_id=thread_id,
                turn_lock=threading.Lock(),
            )
        except Exception:
            if client is not None:
                client.close()
            self._gateway.release(lease.token)
            raise

    def _close_session_resources(self, session: _ManagedSession) -> None:
        try:
            session.client.close()
        finally:
            self._gateway.release(session.lease.token)

    def _catalog_client(self, command: str) -> CodexAppServerClient:
        command_key = _command_key(command)
        with self._lock:
            current = self._catalog_clients.get(command_key)
            if current is not None and current.is_alive():
                return current
            if current is not None:
                current.close()
            client = self._client_factory(command)
            self._catalog_clients[command_key] = client
            return client

    @staticmethod
    def _validate_spec(spec: CodexSessionSpec) -> None:
        for field_name in ("session_key", "provider_id", "model", "command", "cwd", "sandbox", "state_path"):
            if not str(getattr(spec, field_name) or "").strip():
                raise ValueError(f"Codex session {field_name} is required.")
        if not os.path.isdir(spec.cwd):
            raise ValueError(f"Codex working directory does not exist: {spec.cwd}")


def _command_key(command: str) -> str:
    value = str(command or "codex").strip() or "codex"
    if any(separator in value for separator in ("/", "\\")):
        return os.path.normcase(os.path.abspath(value))
    return value.casefold()


__all__ = ["CodexSessionManager", "CodexSessionSpec"]
