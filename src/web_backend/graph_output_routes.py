from __future__ import annotations

from typing import Any

from .route_parser import NodeRouteParser

OutputRoutes = dict[str, list[dict[str, Any]]]


def normalize_output_routes(raw_routes: Any, *, valid_node_ids: set[str] | None = None) -> OutputRoutes:
    if raw_routes is None:
        return {}
    if not isinstance(raw_routes, dict):
        raise ValueError("graph output_routes must be an object")

    normalized: OutputRoutes = {}
    for raw_source_id, raw_items in raw_routes.items():
        source_id = str(raw_source_id or "").strip()
        if not source_id:
            raise ValueError("output_routes source node id is required")
        if valid_node_ids is not None and source_id not in valid_node_ids:
            raise ValueError(f"output_routes source node does not exist: {source_id}")
        if not isinstance(raw_items, list):
            raise ValueError(f"output_routes[{source_id}] must be an array")

        seen_outputs: set[int] = set()
        source_routes: list[dict[str, Any]] = []
        for item_index, item in enumerate(raw_items):
            if not isinstance(item, dict):
                raise ValueError(f"output_routes[{source_id}][{item_index}] must be an object")
            output_index = NodeRouteParser.parse_port_index(item.get("output_index"))
            if output_index is None:
                raise ValueError(f"output_routes[{source_id}][{item_index}].output_index must be a non-negative integer")
            if output_index in seen_outputs:
                raise ValueError(f"output_routes[{source_id}] contains duplicate output_index {output_index}")
            seen_outputs.add(output_index)

            raw_targets = item.get("targets")
            if raw_targets is None:
                raw_targets = []
            if not isinstance(raw_targets, list):
                raise ValueError(f"output_routes[{source_id}][{item_index}].targets must be an array")

            seen_targets: set[tuple[str, int]] = set()
            targets: list[dict[str, Any]] = []
            for target_index, target in enumerate(raw_targets):
                if not isinstance(target, dict):
                    raise ValueError(
                        f"output_routes[{source_id}][{item_index}].targets[{target_index}] must be an object"
                    )
                target_node_id = str(target.get("node_id") or "").strip()
                if not target_node_id:
                    raise ValueError(
                        f"output_routes[{source_id}][{item_index}].targets[{target_index}].node_id is required"
                    )
                if valid_node_ids is not None and target_node_id not in valid_node_ids:
                    raise ValueError(f"output_routes target node does not exist: {target_node_id}")
                input_index = NodeRouteParser.parse_port_index(target.get("input_index", 0))
                if input_index is None:
                    raise ValueError(
                        f"output_routes[{source_id}][{item_index}].targets[{target_index}].input_index "
                        "must be a non-negative integer"
                    )
                target_key = (target_node_id, input_index)
                if target_key in seen_targets:
                    raise ValueError(
                        f"output_routes[{source_id}][{item_index}] contains duplicate target "
                        f"{target_node_id}:{input_index}"
                    )
                seen_targets.add(target_key)
                targets.append({"node_id": target_node_id, "input_index": input_index})

            source_routes.append({"output_index": output_index, "targets": targets})

        if source_routes:
            normalized[source_id] = source_routes

    return normalized


def output_routes_to_outgoing(output_routes: OutputRoutes) -> dict[str, list[dict[str, Any]]]:
    outgoing: dict[str, list[dict[str, Any]]] = {}
    for source_id, routes in output_routes.items():
        for route in routes:
            output_index = NodeRouteParser.parse_port_index(route.get("output_index"))
            if output_index is None:
                raise ValueError(f"output_routes[{source_id}] contains invalid output_index")
            targets = route.get("targets")
            if not isinstance(targets, list):
                raise ValueError(f"output_routes[{source_id}][{output_index}].targets must be an array")
            for target in targets:
                if not isinstance(target, dict):
                    raise ValueError(f"output_routes[{source_id}][{output_index}].targets item must be an object")
                target_node_id = str(target.get("node_id") or "").strip()
                input_index = NodeRouteParser.parse_port_index(target.get("input_index", 0))
                if not target_node_id or input_index is None:
                    raise ValueError(f"output_routes[{source_id}][{output_index}] contains an invalid target")
                outgoing.setdefault(source_id, []).append(
                    {
                        "id": output_route_target_id(source_id, output_index, target_node_id, input_index),
                        "to": target_node_id,
                        "from_output_index": output_index,
                        "to_input_index": input_index,
                    }
                )
    return outgoing


def endpoint_links_to_output_routes(links: list[dict[str, Any]]) -> OutputRoutes:
    routes_by_source_output: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for link in links:
        if not isinstance(link, dict):
            raise ValueError("link item must be an object")
        from_endpoint = link.get("from")
        to_endpoint = link.get("to")
        if not isinstance(from_endpoint, dict) or not isinstance(to_endpoint, dict):
            raise ValueError("link endpoints must be objects")
        source_id = str(from_endpoint.get("node") or "").strip()
        target_node_id = str(to_endpoint.get("node") or "").strip()
        output_index = NodeRouteParser.parse_port_index(from_endpoint.get("index", 0))
        input_index = NodeRouteParser.parse_port_index(to_endpoint.get("index", 0))
        if not source_id or not target_node_id or output_index is None or input_index is None:
            raise ValueError("link endpoints must include node ids and non-negative indexes")
        routes_by_source_output.setdefault((source_id, output_index), []).append(
            {"node_id": target_node_id, "input_index": input_index}
        )

    output_routes: OutputRoutes = {}
    for (source_id, output_index), targets in routes_by_source_output.items():
        output_routes.setdefault(source_id, []).append({"output_index": output_index, "targets": targets})
    return normalize_output_routes(output_routes)


def prune_output_routes_for_removed_node(output_routes: OutputRoutes, node_id: str) -> tuple[OutputRoutes, bool]:
    removed_id = str(node_id or "").strip()
    if not removed_id:
        return output_routes, False
    changed = False
    next_routes: OutputRoutes = {}
    for source_id, routes in output_routes.items():
        if source_id == removed_id:
            changed = True
            continue
        source_routes: list[dict[str, Any]] = []
        for route in routes:
            targets = route.get("targets")
            if not isinstance(targets, list):
                targets = []
            kept_targets = [
                target for target in targets
                if isinstance(target, dict) and str(target.get("node_id") or "").strip() != removed_id
            ]
            if len(kept_targets) != len(targets):
                changed = True
            source_routes.append({"output_index": route.get("output_index"), "targets": kept_targets})
        if source_routes:
            next_routes[source_id] = source_routes
    return normalize_output_routes(next_routes), changed


def rename_output_route_node(output_routes: OutputRoutes, old_node_id: str, new_node_id: str) -> tuple[OutputRoutes, bool]:
    old_id = str(old_node_id or "").strip()
    new_id = str(new_node_id or "").strip()
    if not old_id or not new_id or old_id == new_id:
        return output_routes, False

    changed = False
    renamed: OutputRoutes = {}
    for source_id, routes in output_routes.items():
        next_source_id = new_id if source_id == old_id else source_id
        if next_source_id != source_id:
            changed = True
        source_routes: list[dict[str, Any]] = []
        for route in routes:
            targets = []
            for target in route.get("targets") or []:
                if not isinstance(target, dict):
                    continue
                target_node_id = str(target.get("node_id") or "").strip()
                if target_node_id == old_id:
                    target_node_id = new_id
                    changed = True
                targets.append({"node_id": target_node_id, "input_index": target.get("input_index", 0)})
            source_routes.append({"output_index": route.get("output_index"), "targets": targets})
        existing = renamed.setdefault(next_source_id, [])
        existing.extend(source_routes)
    return normalize_output_routes(renamed), changed


def output_route_target_id(source_id: str, output_index: int, target_node_id: str, input_index: int) -> str:
    return f"route-{source_id}-{int(output_index)}-{target_node_id}-{int(input_index)}"
