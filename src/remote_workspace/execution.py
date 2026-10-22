"""Cancellable workspace execution shared by runtimes and standalone workers."""
import asyncio
import threading
import json

from src.peer_network.remote_contracts import RemoteRequest
from src.remote_worker.protocol import RemoteTask


class WorkspaceExecutor:
    def __init__(self, operations):
        self.operations = operations
        self.active = {}
        self.cancelled = set()
        self.finished = set()
        self.executions = {}

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
        if request.action == "wait":
            execution = self.executions.get(key)
            if execution is None:
                raise ValueError("Unknown remote task; it was not replayed.")
        else:
            if key in self.executions or key in self.finished:
                raise ValueError("Duplicate remote task; execution was not replayed.")
            payload = request.task_payload()
            payload.pop("worker_id")
            task = RemoteTask.from_poll_response({"ok": True, "task": payload})
            cancel = threading.Event()
            if key in self.cancelled:
                self.cancelled.remove(key)
                cancel.set()
            self.active[key] = cancel
            async def run():
                try:
                    return await asyncio.to_thread(self.operations.execute, task, cancel_event=cancel)
                finally:
                    self.active.pop(key, None)
                    self.finished.add(key)
            execution = asyncio.create_task(run())
            self.executions[key] = execution
        # asyncio.wait reports expiry without cancelling the one-and-only execution.
        done, _ = await asyncio.wait({execution}, timeout=request.timeout_seconds)
        if not done:
            return {"result": json.dumps({"status": "running", "remote_task_id": request.task_id, "finished": False})}
        self.executions.pop(key, None)
        return {"result": execution.result()}
