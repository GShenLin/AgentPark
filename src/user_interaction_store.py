"""Durable interaction requests with serialized, single-winner terminal transitions."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from src.file_transaction import atomic_write_text, run_with_interprocess_lock
from src.memory_root import get_memories_root
from src.runtime_cancellation import CancellationRequested, cancel_source_from_agent, raise_if_cancel_requested
from src.user_interaction_schema import validate_interaction_response


def _interaction_dir() -> str:
    path = os.path.join(get_memories_root(), "interactions")
    os.makedirs(path, exist_ok=True)
    return path


def _request_path(request_id: str) -> str:
    if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{32}", request_id):
        raise FileNotFoundError("invalid interaction request id")
    return os.path.join(_interaction_dir(), f"{request_id}.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(path: str, payload: dict) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _read(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("interaction request payload must be an object")
    return payload


def _expire(path: str, payload: dict) -> dict:
    if payload["status"] == "pending" and payload["expires_at"] <= time.time():
        payload.update(status="expired", updated_at=_now_iso(), response={"error": "交互请求已超时"})
        _write(path, payload)
    return payload


def create_interaction_request(*, schema: dict, timeout_sec: int | float, agent: object | None = None) -> dict:
    if isinstance(timeout_sec, bool) or not isinstance(timeout_sec, (int, float)) or not 1 <= timeout_sec <= 3600:
        raise ValueError("timeout_sec must be between 1 and 3600")
    config = getattr(agent, "config", {})
    request_id = uuid.uuid4().hex
    payload = {
        "id": request_id, "status": "pending", "created_at": _now_iso(), "updated_at": _now_iso(),
        "expires_at": time.time() + timeout_sec, "timeout_sec": timeout_sec, "schema": schema,
        "agent": {"graph_id": str(config.get("graph_id") or ""),
                  "node_id": str(config.get("node_instance_id") or config.get("node_id") or ""),
                  "node_name": str(config.get("name") or "")},
        "response": None,
    }
    _write(_request_path(request_id), payload)
    return payload


def read_interaction_request(request_id: str) -> dict:
    path = _request_path(request_id)
    return run_with_interprocess_lock(path + ".lock", lambda: _expire(path, _read(path)))


def list_interaction_requests(status: str = "pending") -> list[dict]:
    if status not in {"pending", "submitted", "cancelled", "expired", "all"}:
        raise ValueError("invalid interaction status")
    items = [read_interaction_request(name[:-5]) for name in os.listdir(_interaction_dir()) if name.endswith(".json")]
    return sorted((item for item in items if status == "all" or item["status"] == status), key=lambda item: item["created_at"])


def submit_interaction_response(request_id: str, response: Any, status: str = "submitted") -> dict:
    if status not in {"submitted", "cancelled", "expired"}:
        raise ValueError(f"invalid interaction status: {status}")
    path = _request_path(request_id)

    def transition() -> dict:
        payload = _expire(path, _read(path))
        if payload["status"] != "pending":
            raise ValueError(f"interaction request is already {payload['status']}")
        validated = validate_interaction_response(payload["schema"], response) if status == "submitted" else response
        if not isinstance(validated, dict):
            raise ValueError("response must be an object")
        payload.update(status=status, updated_at=_now_iso(), response=validated)
        _write(path, payload)
        return payload

    return run_with_interprocess_lock(path + ".lock", transition)


def close_pending_interaction(request_id: str, reason: str, *, status: str = "cancelled") -> dict:
    """Internal cancellation never overwrites an already accepted answer."""
    if status not in {"cancelled", "expired"}:
        raise ValueError("invalid closing status")
    path = _request_path(request_id)

    def transition() -> dict:
        payload = _expire(path, _read(path))
        if payload["status"] == "pending":
            payload.update(status=status, updated_at=_now_iso(), response={"error": reason})
            _write(path, payload)
        return payload

    return run_with_interprocess_lock(path + ".lock", transition)


def interrupt_pending_interactions() -> None:
    for request in list_interaction_requests():
        close_pending_interaction(request["id"], "AgentPark 后端已重启，原交互任务已中断。请重新发起任务。")


def set_interaction_delivery(request_id: str, status: str, error: str = "") -> dict:
    if status not in {"opening", "opened", "failed"}:
        raise ValueError("invalid desktop delivery status")
    path = _request_path(request_id)

    def update() -> dict:
        payload = _expire(path, _read(path))
        payload["desktop"] = {"status": status, "error": error}
        _write(path, payload)
        return payload

    return run_with_interprocess_lock(path + ".lock", update)


def wait_for_interaction_response(request_id: str, *, timeout_sec: int | float, agent: object | None = None) -> dict:
    deadline = time.monotonic() + timeout_sec
    cancel_source = cancel_source_from_agent(agent)
    while True:
        try:
            raise_if_cancel_requested(cancel_source)
        except CancellationRequested:
            return close_pending_interaction(request_id, "Agent 执行已停止")
        payload = read_interaction_request(request_id)
        if payload["status"] != "pending":
            return payload
        if time.monotonic() >= deadline:
            return close_pending_interaction(request_id, "交互请求已超时", status="expired")
        time.sleep(0.2)
