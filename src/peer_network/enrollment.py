"""Device admission is bound to a proved public key, never to a shared token."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Request, Response
from pydantic import Field

from src.file_transaction import atomic_write_text
from .contracts import Contract


class Admission(Contract):
    peer_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    name: str = Field(min_length=1, max_length=100)
    state: Literal["pending", "approved", "rejected"]
    requested_at: int
    last_seen: int


class Decision(Contract):
    state: Literal["approved", "rejected"]


class DeviceAdmissions:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.records: dict[str, Admission] = {}
        self.attempts: dict[str, list[float]] = {}
        if path and path.exists():
            records = [Admission.model_validate(row) for row in json.loads(path.read_text(encoding="utf-8"))]
            self.records = {row.peer_id: row for row in records}
            if len(records) != len(self.records):
                raise ValueError("Duplicate admitted device identity.")

    def save(self) -> None:
        if self.path:
            atomic_write_text(str(self.path), json.dumps([r.model_dump() for r in self.records.values()], ensure_ascii=False))
            self.path.chmod(0o600)

    def prune(self) -> None:
        now = time.time()
        expired = [key for key, row in self.records.items() if row.state == "pending" and now - row.last_seen > 600]
        for key in expired:
            del self.records[key]

    def request(self, identity: str, name: str, address: str) -> str:
        self.prune()
        now = int(time.time())
        existing = self.records.get(identity)
        if existing:
            existing.last_seen = now
            return existing.state
        self.attempts = {key: [t for t in values if now - t < 60] for key, values in self.attempts.items() if values and now - values[-1] < 60}
        if address not in self.attempts and len(self.attempts) >= 1000:
            raise ValueError("Device enrollment rate limit exceeded.")
        attempts = self.attempts.setdefault(address, [])
        if len(attempts) >= 10 or len(self.records) >= 1000 or sum(row.state == "pending" for row in self.records.values()) >= 100:
            raise ValueError("Device enrollment limit exceeded.")
        attempts.append(now)
        self.records[identity] = Admission(peer_id=identity, name=name, state="pending", requested_at=now, last_seen=now)
        self.save()
        return "pending"

    def decide(self, identity: str, state: Literal["approved", "rejected"]) -> None:
        self.prune()
        row = self.records.get(identity)
        if row is None:
            raise KeyError("Device enrollment expired or does not exist.")
        updated = row.model_copy(update={"state": state})
        self.records[identity] = updated
        try:
            self.save()
        except Exception:
            self.records[identity] = row
            raise

    def snapshot(self) -> list[dict]:
        self.prune()
        return [row.model_dump() for row in self.records.values()]


def register_enrollment_routes(app, auth, admissions: DeviceAdmissions):
    @app.get("/portal/api/enrollments")
    async def listing(request: Request, response: Response):
        auth.require_session(request)
        response.headers["Cache-Control"] = "no-store"
        return {"devices": admissions.snapshot()}

    @app.put("/portal/api/enrollments/{device_id}")
    async def decide(device_id: str, decision: Decision, request: Request):
        auth.require_session(request)
        auth.require_origin(request)
        # This endpoint handles pending requests. Revoking live trust is a separate operation.
        row = admissions.records.get(device_id)
        if row and row.state == "approved":
            raise HTTPException(409, "Device is already approved.")
        try:
            admissions.decide(device_id, decision.state)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"peer_id": device_id, "state": decision.state}
