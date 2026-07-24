from __future__ import annotations

import os
from typing import Any

from fastapi import Request

from .graph_output_routes import normalize_output_routes
from .node_config_errors import NodeConfigReadError, NodeConfigWriteError
from .node_config_service import node_config_service
from .request_access import is_local_request
from .service_host import HostBoundService
from .shared import HTTPException


NODE_REFERENCE_FIELDS = {
    "node_id",
    "from_id",
    "to_id",
    "from_node",
    "source_node_id",
    "target_node_id",
    "old_node_id",
    "new_node_id",
}


class NodeVisibilityService(HostBoundService):
    def _node_config_for_visibility(self, graph_id: str, node_id: str) -> tuple[str, str, str]:
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        safe_node_id = self.graph_runtime._sanitize_node_id(node_id)
        config_path = self.graph_runtime._node_config_path(safe_node_id, safe_graph_id)
        return safe_graph_id, safe_node_id, config_path

    def _node_is_private(self, graph_id: str, node_id: str) -> bool:
        _safe_graph_id, _safe_node_id, config_path = self._node_config_for_visibility(graph_id, node_id)
        if not config_path or not os.path.isfile(config_path):
            return False
        try:
            return node_config_service.read_persistent_strict(config_path).get("private") is True
        except NodeConfigReadError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def private_node_ids(self, graph_id: str) -> set[str]:
        safe_graph_id = self.graph_runtime._sanitize_graph_id(graph_id)
        graph_dir = self.graph_runtime._graph_dir(safe_graph_id)
        private_ids: set[str] = set()
        if not graph_dir or not os.path.isdir(graph_dir):
            return private_ids
        for entry in os.listdir(graph_dir):
            if entry == "agents":
                continue
            config_path = os.path.join(graph_dir, entry, "config.json")
            if not os.path.isfile(config_path):
                continue
            try:
                if node_config_service.read_persistent_strict(config_path).get("private") is True:
                    private_ids.add(entry)
            except NodeConfigReadError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
        return private_ids

    def require_node_visible(
        self,
        node_id: str,
        graph_id: str = "",
        request: Request | None = None,
    ) -> None:
        safe_graph_id, safe_node_id, config_path = self._node_config_for_visibility(graph_id, node_id)
        self.core.graph_api.require_graph_visible(safe_graph_id, request)
        if not config_path or not os.path.isfile(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")
        if not is_local_request(request) and self._node_is_private(safe_graph_id, safe_node_id):
            raise HTTPException(status_code=404, detail="node instance not found")

    def set_node_visibility(
        self,
        node_id: str,
        payload: dict,
        graph_id: str = "",
        request: Request = None,
    ) -> dict:
        safe_graph_id, safe_node_id, config_path = self._node_config_for_visibility(graph_id, node_id)
        self.core.graph_api.require_graph_visible(safe_graph_id, request)
        if not is_local_request(request):
            raise HTTPException(status_code=403, detail="node visibility can only be changed from a local client")
        if not config_path or not os.path.isfile(config_path):
            raise HTTPException(status_code=404, detail="node instance not found")
        private = (payload or {}).get("private")
        if not isinstance(private, bool):
            raise HTTPException(status_code=400, detail="private must be a boolean")

        def mutate(next_cfg: dict[str, Any]) -> None:
            next_cfg["private"] = private

        try:
            result = node_config_service.update(config_path, mutate, effective="immediate")
        except NodeConfigReadError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except NodeConfigWriteError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        self.graph_runtime._log_graph_event(
            safe_graph_id,
            "node_visibility_changed",
            node_id=safe_node_id,
            private=private,
        )
        return {
            "ok": True,
            "graph_id": safe_graph_id,
            "node_id": safe_node_id,
            "private": private,
            "changed": result.changed,
        }

    def filter_output_routes_for_request(
        self,
        graph_id: str,
        output_routes: object,
        request: Request | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        routes = normalize_output_routes(output_routes)
        if is_local_request(request):
            return routes
        private_ids = self.private_node_ids(graph_id)
        if not private_ids:
            return routes
        filtered: dict[str, list[dict[str, Any]]] = {}
        for source_id, source_routes in routes.items():
            if source_id in private_ids:
                continue
            next_source_routes: list[dict[str, Any]] = []
            for route in source_routes:
                targets = [
                    dict(target)
                    for target in route.get("targets") or []
                    if isinstance(target, dict)
                    and str(target.get("node_id") or "").strip() not in private_ids
                ]
                next_source_routes.append({"output_index": route.get("output_index"), "targets": targets})
            if next_source_routes:
                filtered[source_id] = next_source_routes
        return normalize_output_routes(filtered)

    def merge_remote_output_routes(
        self,
        graph_id: str,
        incoming_routes: object,
        stored_routes: object,
        request: Request | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        incoming = normalize_output_routes(incoming_routes)
        if is_local_request(request):
            return incoming
        private_ids = self.private_node_ids(graph_id)
        if not private_ids:
            return incoming
        stored = normalize_output_routes(stored_routes)
        merged: dict[str, dict[int, dict[str, Any]]] = {}

        for source_id, source_routes in incoming.items():
            if source_id in private_ids:
                continue
            for route in source_routes:
                output_index = int(route.get("output_index") or 0)
                targets = [
                    dict(target)
                    for target in route.get("targets") or []
                    if isinstance(target, dict)
                    and str(target.get("node_id") or "").strip() not in private_ids
                ]
                merged.setdefault(source_id, {})[output_index] = {
                    "output_index": output_index,
                    "targets": targets,
                }

        for source_id, source_routes in stored.items():
            if source_id in private_ids:
                for route in source_routes:
                    output_index = int(route.get("output_index") or 0)
                    merged.setdefault(source_id, {})[output_index] = {
                        "output_index": output_index,
                        "targets": [dict(target) for target in route.get("targets") or [] if isinstance(target, dict)],
                    }
                continue
            for route in source_routes:
                private_targets = [
                    dict(target)
                    for target in route.get("targets") or []
                    if isinstance(target, dict)
                    and str(target.get("node_id") or "").strip() in private_ids
                ]
                if not private_targets:
                    continue
                output_index = int(route.get("output_index") or 0)
                merged_route = merged.setdefault(source_id, {}).setdefault(
                    output_index,
                    {"output_index": output_index, "targets": []},
                )
                seen = {
                    (str(target.get("node_id") or ""), int(target.get("input_index") or 0))
                    for target in merged_route["targets"]
                    if isinstance(target, dict)
                }
                for target in private_targets:
                    key = (str(target.get("node_id") or ""), int(target.get("input_index") or 0))
                    if key not in seen:
                        merged_route["targets"].append(target)
                        seen.add(key)

        payload = {
            source_id: [routes[index] for index in sorted(routes)]
            for source_id, routes in merged.items()
            if routes
        }
        return normalize_output_routes(payload)

    def sanitize_graph_event_for_request(
        self,
        graph_id: str,
        event: dict[str, Any],
        request: Request | None = None,
    ) -> dict[str, Any]:
        payload = dict(event or {})
        if is_local_request(request):
            return payload
        private_ids = self.private_node_ids(graph_id)
        if not private_ids:
            return payload
        for key in NODE_REFERENCE_FIELDS:
            if str(payload.get(key) or "").strip() in private_ids:
                return {
                    "graph_id": self.graph_runtime._sanitize_graph_id(graph_id),
                    "event": "graph_changed",
                    "version": int(payload.get("version") or 0),
                }
        return payload


__all__ = ["NodeVisibilityService"]
