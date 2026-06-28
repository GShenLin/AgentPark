from __future__ import annotations

import os
import re

from src.web_backend import runtime_paths


def sanitize_graph_id(graph_id: str | None) -> str:
    raw = str(graph_id or "").strip()
    if not raw:
        return "default"
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", raw)
    return safe or "default"


def sanitize_node_id(node_id: str | None) -> str:
    raw = str(node_id or "").strip()
    if not raw:
        return "node"
    safe = re.sub(r'[<>:"/\\|?*]', "_", raw).strip()
    return safe or "node"


def node_config_path(graph_id: str, node_id: str) -> str:
    return os.path.join(runtime_paths._get_graphs_dir(), sanitize_graph_id(graph_id), sanitize_node_id(node_id), "config.json")
