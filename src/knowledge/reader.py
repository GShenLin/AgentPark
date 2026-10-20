"""Transport-independent read operations on an already-authorized library snapshot."""
from pathlib import Path

from .contracts import LibraryConfig
from .database import Database
from .retrieval import read_chunk, search
from .skill_contracts import KnowledgeRequest, ListLibraries, SearchLibrary
from .source_reader import read_source
from .table_contracts import TableQuery
from .table_query import query_table


def read_library(workspace: Path, config: LibraryConfig, directory: Path,
                 request: KnowledgeRequest) -> dict:
    store = Database(directory)
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
