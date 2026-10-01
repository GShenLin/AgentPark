"""Cancellable workspace execution shared by runtimes and standalone workers."""
import asyncio
import threading

from src.peer_network.remote_contracts import RemoteRequest
from src.remote_worker.protocol import RemoteTask


class WorkspaceExecutor:
    def __init__(self, operations):
        self.operations = operations
        self.active = {}
        self.cancelled = set()
        self.finished = set()

    def close(self):
        for cancel in self.active.values():
            cancel.set()

    async def dispatch(self, peer: str, request: RemoteRequest) -> dict:
        key = (peer, request.task_id)
        if request.action == "cancel":
            if key in self.finished:
                return {"state": "completed"}
            event = self.active.get(key)
            if event is not None:
                event.set()
            else:
                if len(self.cancelled) >= 1000:
                    raise RuntimeError("Too many pending cancellation requests.")
                self.cancelled.add(key)
            return {"state": "cancel_requested"}
        if key in self.active or key in self.finished:
            raise ValueError("Duplicate remote task; execution was not replayed.")
        payload = request.task_payload()
        payload.pop("worker_id")
        task = RemoteTask.from_poll_response({"ok": True, "task": payload})
        cancel = threading.Event()
        if key in self.cancelled:
            self.cancelled.remove(key)
            cancel.set()
        self.active[key] = cancel
        execution = asyncio.create_task(asyncio.to_thread(self.operations.execute, task, cancel_event=cancel))
        try:
            async with asyncio.timeout(request.timeout_seconds):
                return {"result": await asyncio.shield(execution)}
        except (asyncio.CancelledError, TimeoutError):
            cancel.set()
            await asyncio.shield(execution)
            raise
        finally:
            self.active.pop(key, None)
            self.finished.add(key)
