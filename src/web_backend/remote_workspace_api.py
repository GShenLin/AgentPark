from __future__ import annotations

import uuid

from fastapi import HTTPException, Request

from src.remote_workspace.broker import RemoteWorkspaceBroker
from src.remote_workspace.peer_bridge import RemotePeerBridge
from src.remote_workspace.directories import DirectoryListing, DirectoryQuery

from .request_access import is_local_request


class RemoteWorkspaceApiDomain:
    def __init__(self, peer_api=None) -> None:
        self.broker = RemoteWorkspaceBroker()
        self.peer_bridge = RemotePeerBridge(peer_api, self.broker) if peer_api is not None else None

    def service_info(self):
        return {"service": "agentpark-runtime", "remote_protocol": 2}

    def list_workers(self, request: Request = None):
        workers = [{**item, "connection_kind": "direct"} for item in self.broker.list_workers()]
        if self.peer_bridge is not None:
            workers.extend(self.peer_bridge.workers())
        return {"workers": workers}

    def _wait_online(self, worker_id: str, timeout: float):
        if worker_id.startswith("peer:"):
            if self.peer_bridge is None:
                raise LookupError("Device interconnection is unavailable.")
            return self.peer_bridge.wait_online(worker_id, timeout)
        return self.broker.wait_for_worker_online(worker_id, timeout)

    def _execute(self, payload: dict):
        if str(payload.get("worker_id", "")).startswith("peer:"):
            if self.peer_bridge is None:
                raise LookupError("Device interconnection is unavailable.")
            return self.peer_bridge.execute(payload)
        return self.broker.execute(payload)

    def register_worker(self, payload: dict, request: Request = None):
        try:
            return {"ok": True, **self.broker.register(payload or {}, _client_ip(request))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def wait_worker_online(self, worker_id: str, payload: dict):
        body = payload if isinstance(payload, dict) else {}
        try:
            worker = self._wait_online(
                worker_id,
                float(body.get("timeout_seconds") or 5.0),
            )
            return {"ok": True, "worker": worker}
        except (LookupError, ConnectionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def poll_worker(self, worker_id: str, payload: dict):
        body = payload if isinstance(payload, dict) else {}
        try:
            task = self.broker.poll(
                worker_id,
                str(body.get("token") or ""),
                float(body.get("timeout_seconds") or 20.0),
            )
            return {"ok": True, "task": task}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def heartbeat_worker(self, worker_id: str, payload: dict):
        body = payload if isinstance(payload, dict) else {}
        try:
            self.broker.heartbeat(worker_id, str(body.get("token") or ""))
            return {"ok": True}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    def poll_worker_cancellations(self, worker_id: str, payload: dict):
        body = payload if isinstance(payload, dict) else {}
        try:
            task_ids = self.broker.poll_cancellations(
                worker_id,
                str(body.get("token") or ""),
                float(body.get("timeout_seconds") or 20.0),
            )
            return {"ok": True, "task_ids": task_ids}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def submit_worker_result(self, worker_id: str, task_id: str, payload: dict):
        body = payload if isinstance(payload, dict) else {}
        result = body.get("result")
        if not isinstance(result, dict):
            raise HTTPException(status_code=400, detail="result must be an object")
        try:
            self.broker.submit_result(worker_id, str(body.get("token") or ""), task_id, result)
            return {"ok": True}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    def list_worker_directories(self, payload: dict, request: Request = None):
        body = payload if isinstance(payload, dict) else {}
        worker_id = str(body.get("worker_id") or "").strip()
        if not worker_id:
            raise HTTPException(status_code=400, detail="worker_id is required")
        try:
            worker = self._wait_online(worker_id, 5)
            query = DirectoryQuery.model_validate({"path": body.get("path", "")})
            if "list_directories" not in worker["capabilities"]:
                raise ValueError("目标设备尚不支持目录浏览，请更新该设备的 AgentPark 或 Remote。")
            result = self._execute(
                {
                    "task_id": uuid.uuid4().hex,
                    "worker_id": worker_id,
                    "tool_name": "list_directories",
                    "working_path": worker["workspace_path"],
                    "arguments": query.model_dump(),
                    "timeout_seconds": 15,
                }
            )
            return DirectoryListing.model_validate_json(result).model_dump()
        except (LookupError, ConnectionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (RuntimeError, TimeoutError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def execute_internal(self, payload: dict, request: Request = None):
        if not is_local_request(request):
            raise HTTPException(status_code=403, detail="remote workspace internal execution is loopback-only")
        try:
            return {"ok": True, "result": self._execute(payload or {})}
        except (LookupError, ConnectionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def cancel_internal_task(self, task_id: str, payload: dict, request: Request = None):
        if not is_local_request(request):
            raise HTTPException(status_code=403, detail="remote workspace internal cancellation is loopback-only")
        body = payload if isinstance(payload, dict) else {}
        try:
            worker_id = str(body.get("worker_id") or "")
            if worker_id.startswith("peer:"):
                if self.peer_bridge is None:
                    raise LookupError("Device interconnection is unavailable.")
                state = self.peer_bridge.cancel(worker_id, task_id)
            else:
                state = self.broker.cancel(worker_id, task_id)
            return {"ok": True, "task_id": task_id, "state": state}
        except LookupError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def close(self) -> None:
        if self.peer_bridge is not None:
            self.peer_bridge.executor.close()
        self.broker.close()


def _client_ip(request: Request | None) -> str:
    client = getattr(request, "client", None)
    return str(getattr(client, "host", "") or "").strip()


__all__ = ["RemoteWorkspaceApiDomain"]
