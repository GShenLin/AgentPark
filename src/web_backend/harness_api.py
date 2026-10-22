from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import partial

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict
from typing import Literal
import os

from src.harness.install_manager import check_installation
from src.harness.jobs import HarnessJobs
from src.harness.registry import DESCRIPTORS, descriptor
from .domain_base import DomainBase
from .request_access import has_owner_access
from .shared import _read_json_dict
from src.harness.contracts import HarnessContext
from src.harness.process_manager import HarnessProcesses


class HarnessOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["install", "upgrade", "uninstall"]


class HarnessProcessOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["start", "stop"]


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

    def list_processes(self, harness_id: str, request: Request):
        self._require_owner(request)
        try:
            descriptor(harness_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"processes": HarnessProcesses.instance().list(harness_id)}

    def _process_target(self, node_id, graph_id):
        graph = self.graph_runtime._sanitize_graph_id(graph_id)
        node = self.graph_runtime._resolve_existing_node_id(graph, node_id)
        path = self.graph_runtime._node_config_path(node, graph)
        config = _read_json_dict(path)
        harness_id = next((item.id for item in DESCRIPTORS if item.node_type == config.get("type_id")), None)
        if harness_id is None:
            raise HTTPException(400, "This node is not a Harness.")
        if config.get("_delete_requested"):
            raise HTTPException(409, "Node is being deleted.")
        return harness_id, HarnessContext(path, os.path.dirname(path),
            {"graph_id": graph, "node_instance_id": node, "access_role": "developer"})

    def process_status(self, node_id: str, request: Request, graph_id: str = ""):
        self._require_owner(request)
        harness_id, context = self._process_target(node_id, graph_id)
        return {"harness_id": harness_id, "graph_id": context.values["graph_id"],
                "node_id": context.values["node_instance_id"],
                **HarnessProcesses.instance().status(context.node_directory)}

    def control_process(self, node_id: str, payload: HarnessProcessOperation,
                        request: Request, graph_id: str = ""):
        self._require_owner(request)
        harness_id, context = self._process_target(node_id, graph_id)
        manager = HarnessProcesses.instance()
        try:
            if payload.action == "start":
                manager.execute(harness_id, context)
            else:
                manager.stop(context.node_directory)
        except (RuntimeError, ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"harness_id": harness_id, "graph_id": context.values["graph_id"],
                "node_id": context.values["node_instance_id"], **manager.status(context.node_directory)}
