from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from .protocol import ProtocolError, normalize_server_origin


@dataclass(frozen=True)
class WorkerIdentity:
    worker_id: str
    token: str = ""
    server_url: str = ""


class IdentityStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load_or_create(self) -> WorkerIdentity:
        if not self.path.exists():
            identity = WorkerIdentity(worker_id=uuid.uuid4().hex)
            self.save(identity)
            return identity
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolError(f"invalid worker identity file: {self.path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ProtocolError(f"worker identity file must contain a JSON object: {self.path}")
        worker_id = str(payload.get("worker_id") or "").strip()
        token = str(payload.get("token") or "").strip()
        server_url = str(payload.get("server_url") or "").strip()
        if not worker_id:
            raise ProtocolError(f"worker identity file is missing worker_id: {self.path}")
        if server_url:
            server_url = normalize_server_origin(server_url)
        return WorkerIdentity(worker_id=worker_id, token=token, server_url=server_url)

    def save(self, identity: WorkerIdentity) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "worker_id": identity.worker_id,
            "token": identity.token,
            "server_url": identity.server_url,
        }
        fd, temporary = tempfile.mkstemp(prefix=".identity_", suffix=".json", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)


class WorkerConfiguration:
    """Thread-safe identity and connection generation shared by discovery/client threads."""

    def __init__(self, store: IdentityStore, identity: WorkerIdentity) -> None:
        self._store = store
        self._identity = identity
        self._generation = 0
        self._condition = threading.Condition()

    def snapshot(self) -> tuple[WorkerIdentity, int]:
        with self._condition:
            return self._identity, self._generation

    def wait_for_server(self, stop_event: threading.Event) -> tuple[WorkerIdentity, int] | None:
        with self._condition:
            while not self._identity.server_url and not stop_event.is_set():
                self._condition.wait(timeout=0.5)
            if stop_event.is_set():
                return None
            return self._identity, self._generation

    def configure_server(self, server_url: str) -> WorkerIdentity:
        normalized = normalize_server_origin(server_url)
        with self._condition:
            if normalized == self._identity.server_url:
                return self._identity
            updated = replace(self._identity, server_url=normalized)
            self._store.save(updated)
            self._identity = updated
            self._generation += 1
            self._condition.notify_all()
            return updated

    def apply_registration(self, *, generation: int, worker_id: str, token: str) -> bool:
        clean_worker_id = str(worker_id or "").strip()
        clean_token = str(token or "").strip()
        if not clean_worker_id or not clean_token:
            raise ProtocolError("registration response must include worker_id and token")
        with self._condition:
            if generation != self._generation:
                return False
            updated = replace(self._identity, worker_id=clean_worker_id, token=clean_token)
            self._store.save(updated)
            self._identity = updated
            self._condition.notify_all()
            return True

    def wake(self) -> None:
        with self._condition:
            self._condition.notify_all()


def default_state_directory() -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if not root:
        root = str(Path.home() / "AppData" / "Local")
    return Path(root) / "AgentParkRemote"
