from __future__ import annotations

import os

from fastapi import Request

from . import runtime_paths
from .graph_config_file import read_graph_config, write_graph_config
from .graph_runtime_registry import GraphConfigReadError
from .request_access import is_local_request
from .service_host import HostBoundService
from .shared import HTTPException


class GraphVisibilityService(HostBoundService):
    def _graph_config_path(self, graph_id: str) -> str:
        return os.path.join(runtime_paths._get_graphs_dir(), graph_id, "config.json")

    def _graph_is_private(self, graph_id: str) -> bool:
        config_path = self._graph_config_path(graph_id)
        if not os.path.exists(config_path):
            return False
        try:
            return read_graph_config(config_path).get("private") is True
        except GraphConfigReadError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def require_graph_visible(self, graph_id: str, request: Request | None = None) -> None:
        safe_id = self.graph_runtime._sanitize_graph_id(graph_id)
        if is_local_request(request):
            return
        if self._graph_is_private(safe_id):
            raise HTTPException(status_code=404, detail="graph not found")

    def set_graph_visibility(self, graph_id: str, payload: dict, request: Request = None):
        safe_id = self.graph_runtime._sanitize_graph_id(graph_id)
        if not safe_id:
            raise HTTPException(status_code=400, detail="invalid graph id")
        if not is_local_request(request):
            raise HTTPException(status_code=403, detail="graph visibility can only be changed from a local client")
        private = (payload or {}).get("private")
        if not isinstance(private, bool):
            raise HTTPException(status_code=400, detail="private must be a boolean")

        config_path = self._graph_config_path(safe_id)
        if os.path.exists(config_path):
            try:
                graph = read_graph_config(config_path)
            except GraphConfigReadError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        elif safe_id == "default":
            graph = {"id": "default", "name": "default", "working_path": "", "output_routes": {}}
        else:
            raise HTTPException(status_code=404, detail="graph not found")

        graph["private"] = private
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        try:
            write_graph_config(config_path, graph)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"ok": True, "graph_id": safe_id, "private": private}


__all__ = ["GraphVisibilityService"]
