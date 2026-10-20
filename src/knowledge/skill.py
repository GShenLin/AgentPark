"""Read-only skill entry points. Library visibility is enforced outside the prompt."""
from pathlib import Path

from .catalog import Catalog
from .reader import read_library
from .skill_contracts import ListLibraries, knowledge_request
from .node_access import selected_libraries


def execute(workspace: Path, arguments: dict, *, library_ids: tuple[str, ...]):
    request = knowledge_request.validate_python(arguments)
    catalog = Catalog(workspace)
    if isinstance(request, ListLibraries) and request.library_id is None:
        return {"libraries": selected_libraries(workspace, library_ids)}
    key = request.library_id
    if key not in library_ids:
        raise PermissionError(f"此知识库未被当前节点勾选：{key}")
    config, directory = catalog.resolve(key)
    return read_library(workspace, config, directory, request)
