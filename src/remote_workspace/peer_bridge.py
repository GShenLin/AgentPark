"""Connect synchronous workspace dispatch to the runtime's authenticated peer loop."""
from __future__ import annotations

import asyncio
import hashlib
from concurrent.futures import TimeoutError as FutureTimeout

from src.peer_network.remote_contracts import RemoteRequest
from .execution import WorkspaceExecutor
from .operations import WorkspaceOperationRegistry


class RemotePeerBridge:
    def __init__(self, peer_api, broker):
        self.peer_api = peer_api
        self.broker = broker
        self.executor = WorkspaceExecutor(WorkspaceOperationRegistry())
        self.runtime_worker_id = ""

    def install(self, service, workspace: str) -> None:
        self.runtime_worker_id = "runtime:" + service.identity.peer_id
        def directory():
            return [{
                "worker_id": self.runtime_worker_id,
                "display_name": service.store.settings.display_name,
                "host_kind": "runtime", "workspace_path": workspace,
                "capabilities": list(self.executor.operations.capabilities), "online": True,
            }, *self.broker.list_workers()]
        service.remote.provider = directory
        service.remote.dispatch = self.accept

    def _run(self, operation, timeout):
        service = self.peer_api.service
        loop = service.event_loop
        if loop is None or not loop.is_running():
            raise ConnectionError("Device interconnection is not running.")
        future = asyncio.run_coroutine_threadsafe(operation(service.remote), loop)
        try:
            return future.result(timeout)
        except FutureTimeout as exc:
            future.cancel()
            raise TimeoutError("Remote device request timed out; it was not replayed.") from exc

    def workers(self) -> list[dict]:
        service = self.peer_api._service
        if service is None or service.socket is None:
            return []
        async def snapshot(remote):
            return remote.workers()
        return self._run(snapshot, 5)

    def wait_online(self, worker_id: str, timeout: float) -> dict:
        return self._run(lambda remote: remote.wait_online(worker_id, timeout), timeout + 5)

    def execute(self, payload: dict):
        request = RemoteRequest.model_validate({"action": "execute", **payload})
        response = self._run(lambda remote: remote.call(request.worker_id, request), request.timeout_seconds + 50)
        if set(response) != {"result"}:
            raise ValueError("Invalid remote execution response.")
        return response["result"]

    def cancel(self, worker_id: str, task_id: str) -> str:
        request = RemoteRequest(action="cancel", worker_id=worker_id, task_id=task_id, timeout_seconds=10.0)
        response = self._run(lambda remote: remote.call(worker_id, request), 50)
        if set(response) != {"state"} or not isinstance(response["state"], str):
            raise ValueError("Invalid remote cancellation response.")
        return response["state"]

    async def accept(self, peer: str, request: RemoteRequest) -> dict:
        if request.worker_id == self.runtime_worker_id:
            return await self.executor.dispatch(peer, request)
        # Each calling runtime owns its task namespace and cancellation rights.
        task_id = hashlib.sha256(f"{peer}:{request.task_id}".encode()).hexdigest()
        if request.action == "cancel":
            return {"state": self.broker.cancel(request.worker_id, task_id)}
        payload = {**request.task_payload(), "task_id": task_id}
        try:
            return {"result": await asyncio.to_thread(self.broker.execute, payload)}
        except asyncio.CancelledError:
            self.broker.cancel(request.worker_id, task_id)
            raise
