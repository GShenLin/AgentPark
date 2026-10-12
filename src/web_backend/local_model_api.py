from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from src import workspace_settings
from src.local_model.contracts import Operation, ServiceConfig
from src.local_model.runtime import LocalModelService
from .request_access import has_owner_access


def register_local_model_routes(app, service: LocalModelService | None = None):
    service = service or LocalModelService(Path(workspace_settings.get_workspace_root()))

    def owner(request: Request):
        if not has_owner_access(request):
            raise HTTPException(403, "本地模型管理需要工作区所有者权限")

    router = APIRouter(prefix="/api/local-model", dependencies=[Depends(owner)])

    def translate(call):
        try:
            return call()
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("")
    def catalog():
        return translate(service.list)

    @router.post("")
    def create(payload: ServiceConfig):
        return translate(lambda: service.save(payload))

    @router.get("/jobs/{job_id}")
    def job(job_id: str):
        return translate(lambda: service.job(job_id))

    @router.put("/{key}")
    def update(key: str, payload: ServiceConfig):
        return translate(lambda: service.save(payload, key))

    @router.delete("/{key}")
    def remove(key: str):
        return translate(lambda: service.remove(key))

    @router.get("/{key}/status")
    def status(key: str):
        return translate(lambda: service.inspect(key))

    @router.post("/{key}/operations")
    def operate(key: str, payload: Operation):
        return translate(lambda: service.operate(key, payload))

    app.include_router(router)
    return service
