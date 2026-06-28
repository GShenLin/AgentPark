from __future__ import annotations

import json
import os

from src.file_transaction import atomic_write_text

from . import runtime_paths
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
        graph_changed = _rename_link_endpoints(graph_cfg, old_node_id, new_node_id) or graph_changed

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


def _rename_link_endpoints(graph_cfg: dict, old_node_id: str, new_node_id: str) -> bool:
    links = graph_cfg.get("links")
    if not isinstance(links, list):
        return False
    changed = False
    for link in links:
        if not isinstance(link, dict):
            continue
        for side in ("from", "to"):
            endpoint = link.get(side)
            if isinstance(endpoint, dict):
                if str(endpoint.get("node") or "").strip() == old_node_id:
                    endpoint["node"] = new_node_id
                    changed = True
            elif isinstance(endpoint, str) and endpoint.strip() == old_node_id:
                link[side] = new_node_id
                changed = True
    return changed
