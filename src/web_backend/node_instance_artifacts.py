from __future__ import annotations

import json
import os

from src.file_transaction import atomic_write_text

from . import runtime_paths
from .graph_output_routes import normalize_output_routes, prune_output_routes_for_removed_node, rename_output_route_node
from .graph_runtime_registry import GraphConfigReadError
from .shared import HTTPException


def rename_node_artifacts(node_dir: str, old_node_id: str, new_node_id: str) -> None:
    old_memory = os.path.join(node_dir, f"{old_node_id}.md")
    new_memory = os.path.join(node_dir, f"{new_node_id}.md")
    try:
        if os.path.exists(old_memory) and not os.path.exists(new_memory):
            os.rename(old_memory, new_memory)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to rename node memory artifact: {str(exc)}")

    old_prefix = f"{old_node_id}_"
    new_prefix = f"{new_node_id}_"
    try:
        filenames = os.listdir(node_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to list node artifacts: {str(exc)}")

    for filename in filenames:
        if not filename.startswith(old_prefix):
            continue
        src_path = os.path.join(node_dir, filename)
        dst_path = os.path.join(node_dir, f"{new_prefix}{filename[len(old_prefix):]}")
        try:
            if not os.path.exists(dst_path):
                os.rename(src_path, dst_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to rename node artifact: {str(exc)}")


def rename_node_references_in_graph(
    graph_runtime: object,
    graph_id: str,
    old_node_id: str,
    new_node_id: str,
    new_name_raw: object,
) -> None:
    try:
        graph_cfg = graph_runtime._read_graph_config(graph_id)
    except GraphConfigReadError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    graph_changed = False
    if isinstance(graph_cfg, dict) and graph_cfg:
        graph_changed = _rename_node_items(graph_cfg, old_node_id, new_node_id, new_name_raw)
        graph_changed = _rename_output_route_references(graph_cfg, old_node_id, new_node_id) or graph_changed
        if graph_cfg.pop("links", None) is not None:
            graph_changed = True

    if not graph_changed:
        return

    graph_dir = os.path.join(runtime_paths._get_graphs_dir(), graph_id)
    os.makedirs(graph_dir, exist_ok=True)
    graph_cfg["id"] = graph_id
    try:
        atomic_write_text(
            os.path.join(graph_dir, "config.json"),
            json.dumps(graph_cfg, ensure_ascii=False, indent=2) + "\n",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to update graph config: {str(exc)}")


def _rename_node_items(graph_cfg: dict, old_node_id: str, new_node_id: str, new_name_raw: object) -> bool:
    nodes = graph_cfg.get("nodes")
    if not isinstance(nodes, list):
        return False
    changed = False
    for node_item in nodes:
        if not isinstance(node_item, dict) or str(node_item.get("id") or "").strip() != old_node_id:
            continue
        node_item["id"] = new_node_id
        if isinstance(new_name_raw, str) and new_name_raw.strip():
            node_item["name"] = new_name_raw.strip()
        changed = True
    return changed


def prune_node_references_in_graph(graph_runtime: object, graph_id: str, node_id: str) -> None:
    try:
        graph_cfg = graph_runtime._read_graph_config(graph_id)
    except GraphConfigReadError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if not isinstance(graph_cfg, dict) or not graph_cfg:
        return

    changed = False
    output_routes = normalize_output_routes(graph_cfg.get("output_routes"))
    next_routes, routes_changed = prune_output_routes_for_removed_node(output_routes, node_id)
    if routes_changed:
        graph_cfg["output_routes"] = next_routes
        changed = True
    if graph_cfg.pop("links", None) is not None:
        changed = True
    if not changed:
        return

    graph_dir = os.path.join(runtime_paths._get_graphs_dir(), graph_id)
    os.makedirs(graph_dir, exist_ok=True)
    graph_cfg["id"] = graph_id
    try:
        atomic_write_text(
            os.path.join(graph_dir, "config.json"),
            json.dumps(graph_cfg, ensure_ascii=False, indent=2) + "\n",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to update graph config: {str(exc)}")


def _rename_output_route_references(graph_cfg: dict, old_node_id: str, new_node_id: str) -> bool:
    output_routes = normalize_output_routes(graph_cfg.get("output_routes"))
    next_routes, changed = rename_output_route_node(output_routes, old_node_id, new_node_id)
    if changed:
        graph_cfg["output_routes"] = next_routes
    return changed
