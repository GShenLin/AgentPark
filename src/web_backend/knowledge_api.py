from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.knowledge.contracts import LibraryConfig, LibraryUpdate, Operation, SearchRequest
from src.knowledge.embedding import Embedder, EmbeddingError
from src.knowledge.retrieval import read_chunk, search
from src.knowledge.service import KnowledgeService
from .request_access import has_owner_access


def register_knowledge_routes(app, service: KnowledgeService):
    def owner(request: Request):
        if not has_owner_access(request):
            raise HTTPException(403, "Knowledge 管理和资料读取需要工作区所有者权限")

    router = APIRouter(prefix="/api/knowledge", dependencies=[Depends(owner)])

    def translate(call):
        try:
            return call()
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except EmbeddingError as exc:
            raise HTTPException(502, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("")
    def libraries():
        return service.list()

    @router.post("")
    def create(payload: LibraryConfig):
        return translate(lambda: service.catalog.create(payload))

    @router.put("/{key}")
    def update(key: str, payload: LibraryUpdate):
        return translate(lambda: service.update(key, payload))

    @router.post("/{key}/test")
    def test_embedding(key: str):
        return translate(lambda: service.test_embedding(key))

    @router.post("/{key}/operations")
    def operation(key: str, payload: Operation):
        return translate(lambda: service.operate(key, payload.action))

    @router.get("/{key}/documents")
    def documents(key: str, after: int = Query(0, ge=0), state: str = "", limit: int = Query(50, ge=1, le=100)):
        if state not in {"", "pending", "parsing", "embedding", "ready", "error"}:
            raise HTTPException(400, "invalid document state")
        return translate(lambda: service.store(key).documents(after, state, limit))

    @router.post("/{key}/search")
    def retrieve(key: str, payload: SearchRequest):
        return translate(lambda: search(service.store(key), service.catalog.get(key), **payload.model_dump(), workspace=service.catalog.workspace))

    @router.get("/{key}/chunks/{chunk_id}")
    def chunk(key: str, chunk_id: int):
        return translate(lambda: read_chunk(service.store(key), chunk_id))

    app.include_router(router)
