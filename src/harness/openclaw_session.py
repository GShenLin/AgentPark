"""Reuse one owned OpenClaw Gateway per native conversation."""
from __future__ import annotations

import atexit
from dataclasses import dataclass, field
import os
from pathlib import Path
import secrets
import socket
import threading
import uuid

from .adapters.cli_session import write_json
from .config import CliRunRequest
from .openclaw_gateway import OpenClawGateway
from .reasoning_config import reasoning_options
from .responses_gateway import HarnessResponsesGateway


@dataclass
class _Session:
    lock: threading.RLock = field(default_factory=threading.RLock)
    signature: tuple = ()
    client: OpenClawGateway | None = None
    token: str = ""
    ready: bool = False


class OpenClawSessions:
    _instance = None
    _instance_lock = threading.Lock()

    def __init__(self, *, gateway=None, client_factory=OpenClawGateway):
        self.gateway = gateway or HarnessResponsesGateway.instance()
        self.client_factory = client_factory
        self.lock = threading.Lock()
        self.sessions: dict[Path, _Session] = {}

    @classmethod
    def instance(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
                atexit.register(cls._instance.close_all)
            return cls._instance

    def is_alive(self, directory) -> bool:
        session = self.sessions.get(Path(directory).resolve())
        return session is not None and session.client is not None and session.client.is_alive()

    def run(self, request: CliRunRequest, argv: list[str], text: str | None, on_event) -> dict:
        key = request.state_dir.resolve()
        efforts = reasoning_options(request.binding.request_config())
        signature = (tuple(argv), request.cwd, request.binding, tuple(efforts), request.reasoning_effort)
        with self.lock:
            session = self.sessions.setdefault(key, _Session())
        with session.lock:
            try:
                if (session.signature != signature or session.client is None
                        or not session.client.is_alive()):
                    self._close(session)
                    self._start(session, request, argv, efforts)
                    session.signature = signature
                if text is None:
                    if not session.ready:
                        session.client.prepare(timeout=request.timeout, cancel_source=request.cancel_source)
                        session.ready = True
                    return {}
                session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(request.state_dir)))
                params = {"message": text, "sessionId": session_id,
                          "sessionKey": f"agent:main:explicit:{session_id}", "deliver": False,
                          "timeout": int(request.timeout), "idempotencyKey": uuid.uuid4().hex}
                if request.reasoning_effort:
                    params["thinking"] = "off" if request.reasoning_effort == "none" else request.reasoning_effort
                return session.client.run(params, timeout=request.timeout,
                                          cancel_source=request.cancel_source, on_event=on_event)
            except BaseException:
                # Never replay an admitted turn. Terminating the owned tree also
                # cancels tools and releases state ownership before the next run.
                self._close(session)
                raise

    def _start(self, session: _Session, request: CliRunRequest, argv: list[str], efforts: list[str]) -> None:
        lease = self.gateway.register(request.binding.provider_id, model=request.binding.model_id,
                                      reasoning_effort=request.reasoning_effort)
        session.token = lease.token
        token = secrets.token_urlsafe(32)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        config_path = request.state_dir / "openclaw.json"
        write_json(config_path, {
            "gateway": {"mode": "local", "bind": "loopback", "port": port,
                        "auth": {"mode": "token", "token": "${AGENTPARK_OPENCLAW_TOKEN}"},
                        "controlUi": {"enabled": False}},
            "models": {"mode": "replace", "providers": {"agentpark": {
                "baseUrl": lease.base_url, "apiKey": "${AGENTPARK_HARNESS_TOKEN}",
                "api": "openai-responses", "models": [{"id": request.binding.model_id,
                    "name": request.binding.model_id, "reasoning": bool(efforts),
                    "compat": {"supportedReasoningEfforts": efforts}}],
            }}},
            "agents": {"defaults": {"workspace": request.cwd,
                "model": {"primary": f"agentpark/{request.binding.model_id}"},
                "heartbeat": {"every": "0m"}}},
            # AgentPark owns scheduling. Keeping a process warm must not create
            # unsolicited model turns when a background command exits.
            "tools": {"exec": {"notifyOnExit": False}},
            "cron": {"enabled": False},
        })
        env = {**os.environ, "OPENCLAW_STATE_DIR": str(request.state_dir),
               "OPENCLAW_CONFIG_PATH": str(config_path), "AGENTPARK_HARNESS_TOKEN": lease.token,
               "AGENTPARK_OPENCLAW_TOKEN": token, "OPENCLAW_DISABLE_BONJOUR": "1",
               "OPENCLAW_SKIP_CHANNELS": "1", "OPENCLAW_NO_RESPAWN": "1"}
        session.client = self.client_factory(argv, cwd=request.cwd, env=env, port=port, token=token)

    def _close(self, session: _Session) -> None:
        if session.client is not None:
            session.client.close()
            session.client = None
        if session.token:
            self.gateway.release(session.token)
            session.token = ""
        session.signature = ()
        session.ready = False

    def close_under(self, directory: str | Path) -> None:
        root = Path(directory).resolve()
        with self.lock:
            sessions = [session for path, session in self.sessions.items() if path.is_relative_to(root)]
        for session in sessions:
            with session.lock:
                self._close(session)

    def close_all(self) -> None:
        with self.lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            with session.lock:
                self._close(session)
