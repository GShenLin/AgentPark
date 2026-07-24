from __future__ import annotations

import os
from pathlib import PurePosixPath

from fastapi import Request
from starlette.responses import PlainTextResponse, Response
from starlette.staticfiles import StaticFiles


class VisibilityAwareMemoriesStaticFiles(StaticFiles):
    def __init__(self, *, directory: str, core: object) -> None:
        super().__init__(directory=directory)
        self._core = core
        self._directory = os.path.abspath(directory)

    async def get_response(self, path: str, scope) -> Response:
        normalized_path = str(path or "").replace("\\", "/").lstrip("/")
        parts = [part for part in PurePosixPath(normalized_path).parts if part not in {"", "."}]
        if parts:
            request = Request(scope)
            graph_id = str(parts[0]).strip()
            try:
                self._core.graph_api.require_graph_visible(graph_id, request)
                if len(parts) >= 2:
                    node_id = str(parts[1]).strip()
                    node_config_path = os.path.join(self._directory, graph_id, node_id, "config.json")
                    if os.path.isfile(node_config_path):
                        self._core.node_ops.require_node_visible(node_id, graph_id, request)
            except Exception as exc:
                if int(getattr(exc, "status_code", 500) or 500) == 404:
                    return PlainTextResponse("Not Found", status_code=404)
                raise
        return await super().get_response(path, scope)


__all__ = ["VisibilityAwareMemoriesStaticFiles"]
