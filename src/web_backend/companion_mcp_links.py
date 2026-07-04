from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from fastapi import HTTPException

from .companion_mcp_errors import CompanionError, companion_error_from_exception
from .graph_output_routes import endpoint_links_to_output_routes, normalize_output_routes, output_routes_to_outgoing
from .route_parser import NodeRouteParser


class CompanionMcpLinkTools:
    def __init__(self, core: object) -> None:
        self.core = core

    def list_link(self, *, graph_id: str = "default") -> dict[str, Any]:
        return self._domain_call(lambda: self._list_link(graph_id=graph_id))

    def connect_node(
        self,
        *,
        graph_id: str = "default",
        from_node: str,
        to_node: str,
        from_output_index: int = 0,
        to_input_index: int = 0,
    ) -> dict[str, Any]:
        return self._domain_call(
            lambda: self._connect_node(
                graph_id=graph_id,
                from_node=from_node,
                to_node=to_node,
                from_output_index=from_output_index,
                to_input_index=to_input_index,
            )
        )

    def disconnect_node(
        self,
        *,
        graph_id: str = "default",
        link_id: str = "",
        from_node: str = "",
        to_node: str = "",
        from_output_index: int = 0,
        to_input_index: int = 0,
    ) -> dict[str, Any]:
        return self._domain_call(
            lambda: self._disconnect_node(
                graph_id=graph_id,
                link_id=link_id,
                from_node=from_node,
                to_node=to_node,
                from_output_index=from_output_index,
                to_input_index=to_input_index,
            )
        )

    def _list_link(self, *, graph_id: str) -> dict[str, Any]:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        graph = self._read_graph(safe_graph_id)
        links = self._normalize_links(graph)
        return {"ok": True, "graph_id": safe_graph_id, "links": links, "count": len(links)}

    def _connect_node(
        self,
        *,
        graph_id: str,
        from_node: str,
        to_node: str,
        from_output_index: int,
        to_input_index: int,
    ) -> dict[str, Any]:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        from_id = self._required_node_id(from_node, field="from_node")
        to_id = self._required_node_id(to_node, field="to_node")
        if from_id == to_id:
            raise CompanionError("invalid_link", "connect_node does not allow linking a node to itself")

        output_index = self._port_index(from_output_index, field="from_output_index")
        input_index = self._port_index(to_input_index, field="to_input_index")
        nodes = self._node_map(safe_graph_id)
        self._validate_endpoint(nodes, from_id, output_index, port_field="output_num", role="from_node")
        self._validate_endpoint(nodes, to_id, input_index, port_field="input_num", role="to_node")

        graph = self._read_graph(safe_graph_id)
        links = self._normalize_links(graph)
        endpoint = {
            "from": {"node": from_id, "index": output_index},
            "to": {"node": to_id, "index": input_index},
        }
        existing = self._find_endpoint_link(links, endpoint)
        if existing is not None:
            return {
                "ok": True,
                "graph_id": safe_graph_id,
                "created": False,
                "link": existing,
                "count": len(links),
            }

        link = {"id": self._new_link_id(links), **endpoint}
        links.append(link)
        self._write_links(safe_graph_id, graph, links, save_reason="companion_connect_node")
        return {"ok": True, "graph_id": safe_graph_id, "created": True, "link": link, "count": len(links)}

    def _disconnect_node(
        self,
        *,
        graph_id: str,
        link_id: str,
        from_node: str,
        to_node: str,
        from_output_index: int,
        to_input_index: int,
    ) -> dict[str, Any]:
        safe_graph_id = self._sanitize_graph_id(graph_id)
        graph = self._read_graph(safe_graph_id)
        links = self._normalize_links(graph)
        safe_link_id = str(link_id or "").strip()
        endpoint: dict[str, dict[str, Any]] | None = None

        if not safe_link_id:
            from_id = self._required_node_id(from_node, field="from_node")
            to_id = self._required_node_id(to_node, field="to_node")
            endpoint = {
                "from": {"node": from_id, "index": self._port_index(from_output_index, field="from_output_index")},
                "to": {"node": to_id, "index": self._port_index(to_input_index, field="to_input_index")},
            }

        kept: list[dict[str, Any]] = []
        removed: list[dict[str, Any]] = []
        for link in links:
            matched = str(link.get("id") or "") == safe_link_id if safe_link_id else self._same_endpoint(link, endpoint)
            if matched:
                removed.append(link)
            else:
                kept.append(link)

        if not removed:
            raise CompanionError(
                "link_not_found",
                "disconnect_node did not find a matching link",
                hint="Call list_link for the graph, then pass link_id or an exact endpoint.",
            )

        self._write_links(safe_graph_id, graph, kept, save_reason="companion_disconnect_node")
        return {
            "ok": True,
            "graph_id": safe_graph_id,
            "removed": removed,
            "removed_count": len(removed),
            "count": len(kept),
        }

    def _read_graph(self, graph_id: str) -> dict[str, Any]:
        graph = self.core.graph_runtime._read_graph_config(graph_id)
        if not isinstance(graph, dict) or (not graph and graph_id != "default"):
            raise CompanionError("graph_not_found", f"graph not found: {graph_id}")
        return dict(graph)

    def _write_links(self, graph_id: str, graph: dict[str, Any], links: list[dict[str, Any]], *, save_reason: str) -> None:
        next_graph = dict(graph)
        next_graph.pop("version", None)
        next_graph.pop("unchanged", None)
        next_graph.pop("nodes", None)
        next_graph["id"] = graph_id
        next_graph["name"] = str(next_graph.get("name") or graph_id)
        next_graph.pop("links", None)
        next_graph["output_routes"] = endpoint_links_to_output_routes(links)
        self.core.graph_api.save_graph(graph_id, {"graph": next_graph, "save_reason": save_reason})

    def _node_map(self, graph_id: str) -> dict[str, dict[str, Any]]:
        payload = self.core.node_ops.list_node_instance_configs(graph_id=graph_id)
        nodes = payload.get("nodes") if isinstance(payload, dict) else None
        if not isinstance(nodes, list):
            raise CompanionError("invalid_graph", f"node list is unavailable for graph: {graph_id}")
        result: dict[str, dict[str, Any]] = {}
        for item in nodes:
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("node_id") or "").strip()
            if node_id:
                result[node_id] = item
        return result

    def _validate_endpoint(
        self,
        nodes: dict[str, dict[str, Any]],
        node_id: str,
        port_index: int,
        *,
        port_field: str,
        role: str,
    ) -> None:
        node = nodes.get(node_id)
        if node is None:
            raise CompanionError("node_not_found", f"{role} does not exist: {node_id}")
        port_count = NodeRouteParser.parse_port_count(node.get(port_field), default=1)
        if port_index >= port_count:
            raise CompanionError(
                "invalid_port",
                f"{role} port index {port_index} is out of range; {port_field}={port_count}",
            )

    def _normalize_links(self, graph: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            outgoing = output_routes_to_outgoing(normalize_output_routes(graph.get("output_routes")))
        except ValueError as exc:
            raise CompanionError("invalid_graph", str(exc)) from exc
        links: list[dict[str, Any]] = []
        for source_id, items in outgoing.items():
            for item in items:
                links.append(
                    {
                        "id": str(item.get("id") or ""),
                        "from": {
                            "node": source_id,
                            "index": self._port_index(item.get("from_output_index"), field="from_output_index"),
                        },
                        "to": {
                            "node": str(item.get("to") or ""),
                            "index": self._port_index(item.get("to_input_index"), field="to_input_index"),
                        },
                    }
                )
        return links

    def _normalize_link(self, item: dict[str, Any], *, index: int) -> dict[str, Any]:
        from_endpoint = self._normalize_endpoint(item.get("from"), field=f"links[{index}].from")
        to_endpoint = self._normalize_endpoint(item.get("to"), field=f"links[{index}].to")
        link_id = str(item.get("id") or "").strip() or self._new_link_id([])
        return {"id": link_id, "from": from_endpoint, "to": to_endpoint}

    def _normalize_endpoint(self, value: object, *, field: str) -> dict[str, Any]:
        if isinstance(value, dict):
            node_id = str(value.get("node") or "").strip()
            raw_index = value.get("index")
        else:
            node_id = str(value or "").strip()
            raw_index = 0
        if not node_id:
            raise CompanionError("invalid_graph", f"{field}.node is required")
        port_index = NodeRouteParser.parse_port_index(raw_index)
        if port_index is None:
            raise CompanionError("invalid_graph", f"{field}.index must be a non-negative integer")
        return {"node": node_id, "index": port_index}

    def _required_node_id(self, value: object, *, field: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            raise CompanionError("invalid_request", f"{field} is required")
        return self.core.graph_runtime._sanitize_node_id(raw)

    def _sanitize_graph_id(self, value: object) -> str:
        return self.core.graph_runtime._sanitize_graph_id(value)

    @staticmethod
    def _port_index(value: object, *, field: str) -> int:
        port_index = NodeRouteParser.parse_port_index(value)
        if port_index is None:
            raise CompanionError("invalid_request", f"{field} must be a non-negative integer")
        return port_index

    @staticmethod
    def _find_endpoint_link(links: list[dict[str, Any]], endpoint: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        for link in links:
            if CompanionMcpLinkTools._same_endpoint(link, endpoint):
                return link
        return None

    @staticmethod
    def _same_endpoint(link: dict[str, Any], endpoint: dict[str, dict[str, Any]] | None) -> bool:
        if endpoint is None:
            return False
        return (
            str((link.get("from") or {}).get("node") or "") == endpoint["from"]["node"]
            and int((link.get("from") or {}).get("index") or 0) == endpoint["from"]["index"]
            and str((link.get("to") or {}).get("node") or "") == endpoint["to"]["node"]
            and int((link.get("to") or {}).get("index") or 0) == endpoint["to"]["index"]
        )

    @staticmethod
    def _endpoint_key(link: dict[str, Any]) -> tuple[str, int, str, int]:
        return (
            str((link.get("from") or {}).get("node") or ""),
            int((link.get("from") or {}).get("index") or 0),
            str((link.get("to") or {}).get("node") or ""),
            int((link.get("to") or {}).get("index") or 0),
        )

    @staticmethod
    def _new_link_id(existing_links: list[dict[str, Any]]) -> str:
        existing = {str(item.get("id") or "") for item in existing_links if isinstance(item, dict)}
        while True:
            candidate = f"link-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"
            if candidate not in existing:
                return candidate

    @staticmethod
    def _domain_call(func: Callable[[], Any]) -> Any:
        try:
            return func()
        except HTTPException as exc:
            return companion_error_from_exception(exc).to_result()
        except Exception as exc:
            return companion_error_from_exception(exc).to_result()


__all__ = ["CompanionMcpLinkTools"]
