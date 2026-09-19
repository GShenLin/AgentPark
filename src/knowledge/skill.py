"""Read-only skill entry points. Library visibility is enforced outside the prompt."""
from pathlib import Path

from .catalog import Catalog
from .database import Database
from .retrieval import read_chunk, search
from .skill_contracts import ListLibraries, SearchLibrary, knowledge_request
from .source_reader import read_source
from .table_contracts import TableQuery
from .table_query import query_table


def execute(workspace: Path, arguments: dict):
    request = knowledge_request.validate_python(arguments)
    catalog = Catalog(workspace)
    if isinstance(request, ListLibraries) and request.library_id is None:
        return {"libraries": [{"id": item["id"], "name": item["name"],
                               "embedding_model": item["embedding_model"]}
                              for item in catalog.list() if item["allow_agents"]]}
    key = request.library_id
    config = catalog.get(key)
    if not config.allow_agents:
        raise PermissionError("此知识库未向 Agent Skill 开放")
    store = Database(catalog.directory(key))
    if not store.path.is_file():
        raise ValueError("知识库尚未建立索引，请在 Knowledge 设置中启动扫描")
    store.initialize()
    if isinstance(request, ListLibraries):
        return store.documents(after=request.after, limit=request.limit)
    if isinstance(request, SearchLibrary):
        return search(store, config, request.query, request.limit, request.mode, workspace=workspace)
    if isinstance(request, TableQuery):
        return query_table(store, config, request)
    if request.document_id is not None:
        return read_source(store, config, request)
    return read_chunk(store, request.chunk_id)
