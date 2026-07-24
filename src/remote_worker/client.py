from __future__ import annotations

import json
import logging
import platform
import threading
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .identity import WorkerConfiguration, WorkerIdentity
from .operations import StandaloneOperationRegistry
from .protocol import PROTOCOL_VERSION, ProtocolError, RemoteTask, decode_json_object, require_object


POLL_TIMEOUT_SECONDS = 20.0
HEARTBEAT_INTERVAL_SECONDS = 10.0
RETRY_DELAY_SECONDS = 3.0
MAX_HTTP_RESPONSE_BYTES = 4 * 1024 * 1024


class RemoteHttpError(RuntimeError):
    def __init__(self, status_code: int | None, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code


class JsonHttpTransport:
    def post(self, url: str, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=max(1.0, float(timeout))) as response:
                data = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            detail = exc.read(64 * 1024).decode("utf-8", errors="replace").strip()
            raise RemoteHttpError(exc.code, detail or f"HTTP {exc.code}") from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise RemoteHttpError(None, f"{type(exc).__name__}: {exc}") from exc
        if len(data) > MAX_HTTP_RESPONSE_BYTES:
            raise ProtocolError(f"HTTP response exceeds {MAX_HTTP_RESPONSE_BYTES} bytes")
        return decode_json_object(data, "HTTP response")


@dataclass(frozen=True)
class RegisteredSession:
    identity: WorkerIdentity
    generation: int


class RemoteWorkerClient:
    def __init__(
        self,
        configuration: WorkerConfiguration,
        operations: StandaloneOperationRegistry,
        *,
        workspace_path: str,
        display_name: str,
        transport: JsonHttpTransport | None = None,
        logger: logging.Logger | None = None,
        retry_delay_seconds: float = RETRY_DELAY_SECONDS,
    ) -> None:
        self._configuration = configuration
        self._operations = operations
        self._workspace_path = workspace_path
        self._display_name = display_name
        self._transport = transport or JsonHttpTransport()
        self._logger = logger or logging.getLogger(__name__)
        self._retry_delay_seconds = max(0.05, float(retry_delay_seconds))
        self._stop_event = threading.Event()
        self._session_lock = threading.Lock()
        self._session: RegisteredSession | None = None
        self._heartbeat_thread: threading.Thread | None = None

    def run_forever(self) -> None:
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="remote-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()
        while not self._stop_event.is_set():
            pending = self._configuration.wait_for_server(self._stop_event)
            if pending is None:
                break
            identity, generation = pending
            try:
                session = self._register(identity, generation)
                if session is None:
                    continue
                self._set_session(session)
                self._poll_session(session)
            except Exception:
                self._logger.exception("AgentPark Remote connection cycle failed for %s", identity.server_url)
            finally:
                self._clear_session(generation)
            self._stop_event.wait(self._retry_delay_seconds)

    def stop(self) -> None:
        self._stop_event.set()
        self._configuration.wake()
        thread = self._heartbeat_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    def _register(self, identity: WorkerIdentity, generation: int) -> RegisteredSession | None:
        response = self._transport.post(
            identity.server_url + "/api/remote-workers/register",
            {
                "protocol_version": PROTOCOL_VERSION,
                "worker_id": identity.worker_id,
                "token": identity.token,
                "display_name": self._display_name,
                "host_kind": "standalone",
                "workspace_path": self._workspace_path,
                "capabilities": list(self._operations.capabilities),
            },
            timeout=15.0,
        )
        if response.get("ok") is not True:
            raise ProtocolError("registration response did not report ok=true")
        protocol_version = response.get("protocol_version")
        if isinstance(protocol_version, bool) or protocol_version != PROTOCOL_VERSION:
            raise ProtocolError(f"registration returned unsupported protocol_version: {protocol_version!r}")
        worker_id = response.get("worker_id")
        token = response.get("token")
        if not isinstance(worker_id, str) or not isinstance(token, str):
            raise ProtocolError("registration response worker_id and token must be strings")
        if not self._configuration.apply_registration(
            generation=generation,
            worker_id=worker_id,
            token=token,
        ):
            return None
        current, current_generation = self._configuration.snapshot()
        if current_generation != generation:
            return None
        self._logger.info("Connected to %s as %s", current.server_url, self._display_name)
        return RegisteredSession(identity=current, generation=generation)

    def _poll_session(self, session: RegisteredSession) -> None:
        worker_id = quote(session.identity.worker_id, safe="")
        poll_url = session.identity.server_url + f"/api/remote-workers/{worker_id}/poll"
        while self._is_current(session):
            response = self._transport.post(
                poll_url,
                {"token": session.identity.token, "timeout_seconds": POLL_TIMEOUT_SECONDS},
                timeout=POLL_TIMEOUT_SECONDS + 10.0,
            )
            task = RemoteTask.from_poll_response(response)
            if task is None:
                continue
            self._execute_and_submit(session, task)

    def _execute_and_submit(self, session: RegisteredSession, task: RemoteTask) -> None:
        try:
            result = self._operations.execute(task)
            envelope: dict[str, Any] = {"ok": True, "result": result}
        except Exception as exc:
            self._logger.exception("Remote tool %s failed for task %s", task.tool_name, task.task_id)
            envelope = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if not self._is_current(session):
            self._logger.warning("Discarding task result after AgentPark server changed: %s", task.task_id)
            return
        worker_id = quote(session.identity.worker_id, safe="")
        task_id = quote(task.task_id, safe="")
        url = session.identity.server_url + f"/api/remote-workers/{worker_id}/tasks/{task_id}/result"
        response = self._transport.post(
            url,
            {"token": session.identity.token, "result": envelope},
            timeout=30.0,
        )
        if response.get("ok") is not True:
            raise ProtocolError("task result response did not report ok=true")

    def _heartbeat_loop(self) -> None:
        while not self._stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
            session = self._get_session()
            if session is None or not self._is_current(session):
                continue
            worker_id = quote(session.identity.worker_id, safe="")
            url = session.identity.server_url + f"/api/remote-workers/{worker_id}/heartbeat"
            try:
                response = self._transport.post(
                    url,
                    {"token": session.identity.token},
                    timeout=10.0,
                )
                require_object(response, "heartbeat response")
                if response.get("ok") is not True:
                    raise ProtocolError("heartbeat response did not report ok=true")
            except Exception:
                self._logger.exception("AgentPark Remote heartbeat failed for %s", session.identity.server_url)

    def _is_current(self, session: RegisteredSession) -> bool:
        if self._stop_event.is_set():
            return False
        identity, generation = self._configuration.snapshot()
        return generation == session.generation and identity.server_url == session.identity.server_url

    def _set_session(self, session: RegisteredSession) -> None:
        with self._session_lock:
            self._session = session

    def _get_session(self) -> RegisteredSession | None:
        with self._session_lock:
            return self._session

    def _clear_session(self, generation: int) -> None:
        with self._session_lock:
            if self._session is not None and self._session.generation == generation:
                self._session = None


def default_display_name(workspace_path: str) -> str:
    folder = workspace_path.rstrip("\\/").split("\\")[-1].split("/")[-1] or workspace_path
    return f"{platform.node() or 'Windows PC'} / {folder}"
