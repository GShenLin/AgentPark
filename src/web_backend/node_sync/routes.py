from fastapi import APIRouter, HTTPException, Request

from .contracts import CreateGraph, SyncRequest
from .jobs import SyncJobs
from .service import SyncService
from .cloud import CloudLogin


def register_node_sync_routes(app, core, *, service=None):
    router = APIRouter(prefix="/api/node-sync", tags=["node-sync"])
    service = service or SyncService(core)
    jobs = SyncJobs(service)

    def invoke(operation):
        try:
            return operation()
        except (ValueError, KeyError, FileNotFoundError, ConnectionError, TimeoutError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/protocol/{operation}")
    def protocol(operation: str, payload: dict, request: Request):
        return invoke(lambda: service.protocol(operation, payload, request))

    @router.get("/remotes")
    def remotes(request: Request):
        core.access_api.require_developer(request)
        return invoke(lambda: jobs.remotes(request))

    @router.get("/cloud")
    def cloud_status(request: Request):
        return invoke(lambda: jobs.cloud.status(request))

    @router.post("/cloud/login")
    def cloud_login(payload: CloudLogin, request: Request):
        return invoke(lambda: jobs.cloud.login(request, payload.password.get_secret_value()))

    @router.post("/cloud/logout")
    def cloud_logout(request: Request):
        return invoke(lambda: jobs.cloud.logout(request))

    @router.get("/catalog/{remote_id}")
    def catalog(remote_id: str, request: Request, graph_id: str = ""):
        core.access_api.require_developer(request)
        return invoke(lambda: jobs.call(remote_id, "catalog", {"graph_id": graph_id} if graph_id else {}, request))

    @router.post("/jobs")
    def create(payload: SyncRequest, request: Request):
        core.access_api.require_developer(request)
        return invoke(lambda: jobs.create(payload, request))

    @router.post("/catalog/{remote_id}/graphs")
    def create_graph(remote_id: str, payload: CreateGraph, request: Request):
        core.access_api.require_developer(request)
        return invoke(lambda: jobs.call(remote_id, "create-graph", payload.model_dump(), request))

    @router.get("/jobs/{job_id}")
    def status(job_id: str, request: Request):
        core.access_api.require_developer(request)
        return invoke(lambda: jobs.get(job_id, request))

    @router.post("/jobs/{job_id}/{action}")
    def start(job_id: str, action: str, request: Request):
        core.access_api.require_developer(request)
        if action not in {"commit", "preview"}:
            raise HTTPException(400, "invalid sync action")
        invoke(lambda: jobs.launch(job_id, action, request))
        return jobs.get(job_id, request)

    app.include_router(router)
    return jobs
