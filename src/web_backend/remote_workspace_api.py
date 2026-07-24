from __future__ import annotations

import json

from fastapi import HTTPException, Request

from src.remote_workspace.broker import RemoteWorkspaceBroker

from .request_access import is_local_request


class RemoteWorkspaceApiDomain:
    def __init__(self) -> None:
        self.broker = RemoteWorkspaceBroker()

    def list_workers(self, request: Request = None):
        return {"workers": self.broker.list_for_ip(_client_ip(request))}

    def pair_worker(self, request: Request = None):
        try:
            return {"ok": True, "worker": self.broker.pair_for_ip(_client_ip(request))}
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def register_worker(self, payload: dict, request: Request = None):
        try:
            return {"ok": True, **self.broker.register(payload or {}, _client_ip(request))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def wait_worker_online(self, worker_id: str, payload: dict):
        body = payload if isinstance(payload, dict) else {}
        try:
            worker = self.broker.wait_for_worker_online(
                worker_id,
                float(body.get("timeout_seconds") or 5.0),
            )
            return {"ok": True, "worker": worker}
        except LookupError as exc:
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

    def select_worker_folder(self, payload: dict, request: Request = None):
        body = payload if isinstance(payload, dict) else {}
        worker_id = str(body.get("worker_id") or "").strip()
        if not worker_id:
            raise HTTPException(status_code=400, detail="worker_id is required")
        try:
            self.broker.require_worker_for_ip(worker_id, _client_ip(request))
            result = self.broker.execute(
                {
                    "worker_id": worker_id,
                    "tool_name": "select_folder",
                    "working_path": str(body.get("initial_path") or body.get("working_path") or ".").strip() or ".",
                    "arguments": {"initial_path": str(body.get("initial_path") or "")},
                    "timeout_seconds": 300,
                }
            )
            decoded = _decode_result_object(result)
            return {"ok": True, "path": str(decoded.get("path") or "")}
        except LookupError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (RuntimeError, TimeoutError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def execute_internal(self, payload: dict, request: Request = None):
        if not is_local_request(request):
            raise HTTPException(status_code=403, detail="remote workspace internal execution is loopback-only")
        try:
            return {"ok": True, "result": self.broker.execute(payload or {})}
        except LookupError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def close(self) -> None:
        self.broker.close()


def _client_ip(request: Request | None) -> str:
    client = getattr(request, "client", None)
    return str(getattr(client, "host", "") or "").strip()


def _decode_result_object(result: object) -> dict:
    if isinstance(result, dict):
        return result
    if isinstance(result, str) and result.strip():
        try:
            decoded = json.loads(result)
        except json.JSONDecodeError as exc:
            raise ValueError("remote worker returned invalid select_folder JSON") from exc
        if isinstance(decoded, dict):
            return decoded
    raise ValueError("remote worker select_folder result must be an object")


__all__ = ["RemoteWorkspaceApiDomain"]
