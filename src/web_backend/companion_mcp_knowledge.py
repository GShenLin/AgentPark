"""Public knowledge access through AgentPark's own MCP endpoint."""
from src.knowledge.reader import read_library
from src.knowledge.skill_contracts import KnowledgeRequest, ListLibraries

from .companion_mcp_errors import CompanionError


class CompanionKnowledgeTools:
    def __init__(self, core: object):
        self.core = core

    def get_knowledge(self, request: KnowledgeRequest | None = None) -> dict:
        catalog = self.core.knowledge_service.catalog
        if request is None or isinstance(request, ListLibraries) and request.library_id is None:
            return {
                "libraries": [
                    {"id": item["id"], "name": item["name"], "access": "read_only"}
                    for item in catalog.list() if item["allow_mcp"]
                ],
                "usage": {
                    "tool": "get_knowledge",
                    "request": "Pass an action and library_id in the request object.",
                    "actions": {
                        "list": "List documents with library_id, after and limit; omit library_id to discover libraries.",
                        "search": "Search with library_id, query, mode (hybrid/semantic/keyword), limit.",
                        "read": "Read with library_id and exactly one of chunk_id or document_id; document reads support sheet, offset, limit.",
                        "table": "Aggregate Excel data with library_id, document_id, sheet, metrics; optionally rows, filters, group_by.",
                    },
                    "access": "Only libraries currently allowing MCP access are available. No node or Skill activation is needed.",
                },
            }
        try:
            config, directory = catalog.resolve(request.library_id)
        except KeyError as exc:
            raise CompanionError("knowledge_not_available", "此知识库不存在或未允许通过 MCP 访问") from exc
        if not config.allow_mcp:
            raise CompanionError("knowledge_not_available", "此知识库不存在或未允许通过 MCP 访问")
        return read_library(catalog.workspace, config, directory, request)
