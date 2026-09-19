from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import partial

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict
from typing import Literal

from src.harness.install_manager import check_installation
from src.harness.jobs import HarnessJobs
from src.harness.registry import DESCRIPTORS, descriptor
from .domain_base import DomainBase
from .request_access import has_owner_access


class HarnessOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["install", "upgrade", "uninstall"]


class HarnessApiDomain(DomainBase):
    def __init__(self, core):
        super().__init__(core)
        self._jobs = HarnessJobs()

    @staticmethod
    def _require_owner(request: Request | None):
        if not has_owner_access(request):
            raise HTTPException(403, "Harness management requires workspace owner access.")

    def list_harnesses(self, request: Request):
        self._require_owner(request)
        with ThreadPoolExecutor(max_workers=5) as pool:
            harnesses = list(pool.map(partial(check_installation, include_updates=True), [item.id for item in DESCRIPTORS]))
        return {"harnesses": harnesses, "jobs": self._jobs.list()}

    def check_harness(self, harness_id: str, request: Request):
        self._require_owner(request)
        try:
            descriptor(harness_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return check_installation(harness_id, include_updates=True)

    def operate_harness(self, harness_id: str, payload: HarnessOperation, request: Request):
        self._require_owner(request)
        try:
            return self._jobs.start(harness_id, payload.action)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    def get_job(self, job_id: str, request: Request):
        self._require_owner(request)
        try:
            return self._jobs.get(job_id)
        except KeyError as exc:
            raise HTTPException(404, "Harness installation job not found.") from exc
