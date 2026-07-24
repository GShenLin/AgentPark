from __future__ import annotations

import secrets
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any


PROTOCOL_VERSION = 1
ONLINE_TTL_SECONDS = 45.0
RECONNECT_WAIT_SECONDS = 5.0


@dataclass
class RemoteTask:
    task_id: str
    payload: dict[str, Any]
    created_at: float = field(default_factory=time.monotonic)


@dataclass
class WorkerSession:
    worker_id: str
    token: str
    source_ip: str
    display_name: str
    host_kind: str
    workspace_path: str
    capabilities: frozenset[str]
    last_seen: float = field(default_factory=time.monotonic)
    pending: deque[RemoteTask] = field(default_factory=deque)
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    condition: threading.Condition = field(default_factory=threading.Condition)


class RemoteWorkspaceBroker:
    def __init__(self) -> None:
        self._workers: dict[str, WorkerSession] = {}
        self._lock = threading.RLock()
        self._worker_state_changed = threading.Condition(self._lock)
        self._closed = False

    def register(self, payload: dict[str, Any], source_ip: str) -> dict[str, Any]:
        protocol_version = int(payload.get("protocol_version") or 0)
        if protocol_version != PROTOCOL_VERSION:
            raise ValueError(f"unsupported remote worker protocol_version: {protocol_version}")
        worker_id = str(payload.get("worker_id") or "").strip()
        if not worker_id:
            worker_id = uuid.uuid4().hex
        token = str(payload.get("token") or "").strip() or secrets.token_urlsafe(32)
        workspace_path = str(payload.get("workspace_path") or "").strip()
        if not workspace_path:
            raise ValueError("workspace_path is required")
        capabilities = frozenset(
            str(item or "").strip()
            for item in (payload.get("capabilities") or [])
            if str(item or "").strip()
        )
        with self._worker_state_changed:
            existing = self._workers.get(worker_id)
            if existing is not None and existing.token != token and self._is_online(existing):
                raise ValueError(f"worker_id is already online: {worker_id}")
            session = WorkerSession(
                worker_id=worker_id,
                token=token,
                source_ip=str(source_ip or "").strip(),
                display_name=str(payload.get("display_name") or worker_id).strip() or worker_id,
                host_kind=str(payload.get("host_kind") or "worker").strip() or "worker",
                workspace_path=workspace_path,
                capabilities=capabilities,
            )
            self._workers[worker_id] = session
            self._worker_state_changed.notify_all()
        return {"worker_id": worker_id, "token": token, "protocol_version": PROTOCOL_VERSION}

    def wait_for_worker_online(
        self,
        worker_id: str,
        timeout_seconds: float = RECONNECT_WAIT_SECONDS,
    ) -> dict[str, Any]:
        worker_key = str(worker_id or "").strip()
        if not worker_key:
            raise ValueError("worker_id is required")
        return self._public_worker(self._wait_for_session(worker_key, timeout_seconds))

    def list_for_ip(self, source_ip: str) -> list[dict[str, Any]]:
        ip = str(source_ip or "").strip()
        with self._lock:
            return [self._public_worker(item) for item in self._workers.values() if item.source_ip == ip and self._is_online(item)]

    def pair_for_ip(self, source_ip: str) -> dict[str, Any]:
        workers = self.list_for_ip(source_ip)
        if not workers:
            raise LookupError(
                "No online AgentPark remote worker was found for this browser IP. "
                "Start AgentParkRemote or open an application plugin that provides the AgentPark remote worker protocol."
            )
        if len(workers) != 1:
            names = ", ".join(str(item.get("display_name") or item.get("worker_id")) for item in workers)
            raise RuntimeError(f"Multiple remote workers are online for this IP; keep only one open before pairing: {names}")
        return workers[0]

    def require_worker_for_ip(self, worker_id: str, source_ip: str) -> dict[str, Any]:
        worker_key = str(worker_id or "").strip()
        ip = str(source_ip or "").strip()
        with self._lock:
            session = self._workers.get(worker_key)
        if session is None or not self._is_online(session):
            raise LookupError(f"Remote worker is offline: {worker_key}")
        if session.source_ip != ip:
            raise PermissionError("Remote worker does not belong to this browser IP.")
        return self._public_worker(session)

    def poll(self, worker_id: str, token: str, timeout_seconds: float) -> dict[str, Any] | None:
        session = self._require_worker(worker_id, token)
        deadline = time.monotonic() + max(0.0, min(float(timeout_seconds), 25.0))
        with session.condition:
            session.last_seen = time.monotonic()
            while not self._closed and not session.pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                session.condition.wait(timeout=remaining)
                session.last_seen = time.monotonic()
            if self._closed or not session.pending:
                return None
            task = session.pending.popleft()
            return {"task_id": task.task_id, **task.payload}

    def heartbeat(self, worker_id: str, token: str) -> None:
        session = self._require_worker(worker_id, token)
        with session.condition:
            session.last_seen = time.monotonic()
            session.condition.notify_all()

    def submit_result(self, worker_id: str, token: str, task_id: str, result: dict[str, Any]) -> None:
        session = self._require_worker(worker_id, token)
        with session.condition:
            session.last_seen = time.monotonic()
            session.results[str(task_id)] = dict(result)
            session.condition.notify_all()

    def execute(self, payload: dict[str, Any]) -> Any:
        worker_id = str(payload.get("worker_id") or "").strip()
        tool_name = str(payload.get("tool_name") or "").strip()
        working_path = str(payload.get("working_path") or "").strip()
        if not worker_id or not tool_name or not working_path:
            raise ValueError("worker_id, tool_name and working_path are required")
        session = self._wait_for_session(worker_id, RECONNECT_WAIT_SECONDS)
        if tool_name not in session.capabilities:
            raise ValueError(f"Remote worker does not support tool: {tool_name}")
        timeout_seconds = max(1.0, min(float(payload.get("timeout_seconds") or 3600.0), 86400.0))
        task_id = uuid.uuid4().hex
        task = RemoteTask(
            task_id=task_id,
            payload={
                "tool_name": tool_name,
                "arguments": payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {},
                "working_path": working_path,
                "timeout_seconds": timeout_seconds,
            },
        )
        deadline = time.monotonic() + timeout_seconds
        try:
            with session.condition:
                session.pending.append(task)
                session.condition.notify_all()
                while not self._closed:
                    result = session.results.pop(task_id, None)
                    if result is not None:
                        if bool(result.get("ok")):
                            return result.get("result")
                        raise RuntimeError(str(result.get("error") or "Remote worker task failed."))
                    if not self._is_online(session):
                        raise LookupError(f"Remote worker disconnected while executing {tool_name}: {worker_id}")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(f"Remote worker tool execution exceeded {timeout_seconds:g}s: {tool_name}")
                    session.condition.wait(timeout=min(1.0, remaining))
        finally:
            with session.condition:
                session.results.pop(task_id, None)
        raise RuntimeError("Remote workspace broker is shutting down.")

    def close(self) -> None:
        with self._worker_state_changed:
            self._closed = True
            sessions = list(self._workers.values())
            self._worker_state_changed.notify_all()
        for session in sessions:
            with session.condition:
                session.condition.notify_all()

    def _require_worker(self, worker_id: str, token: str) -> WorkerSession:
        with self._lock:
            session = self._workers.get(str(worker_id or "").strip())
        if session is None or not secrets.compare_digest(session.token, str(token or "")):
            raise PermissionError("invalid remote worker credentials")
        return session

    def _wait_for_session(self, worker_id: str, timeout_seconds: float) -> WorkerSession:
        worker_key = str(worker_id or "").strip()
        timeout = max(0.0, min(float(timeout_seconds), 30.0))
        deadline = time.monotonic() + timeout
        with self._worker_state_changed:
            while not self._closed:
                session = self._workers.get(worker_key)
                if session is not None and self._is_online(session):
                    return session
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._worker_state_changed.wait(timeout=remaining)
        raise LookupError(f"Remote worker did not reconnect within {timeout:g}s: {worker_key}")

    @staticmethod
    def _is_online(session: WorkerSession) -> bool:
        return time.monotonic() - session.last_seen <= ONLINE_TTL_SECONDS

    def _public_worker(self, session: WorkerSession) -> dict[str, Any]:
        return {
            "worker_id": session.worker_id,
            "display_name": session.display_name,
            "host_kind": session.host_kind,
            "workspace_path": session.workspace_path,
            "capabilities": sorted(session.capabilities),
            "online": self._is_online(session),
        }
