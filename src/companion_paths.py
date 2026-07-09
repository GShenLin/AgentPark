from __future__ import annotations

import os


COMPANION_GRAPH_ID = "Companion"
COMPANION_NODE_ID = "Companion"


def companion_graph_config_path(graphs_dir: str) -> str:
    return os.path.join(graphs_dir, COMPANION_GRAPH_ID, "config.json")


def companion_node_dir(graphs_dir: str) -> str:
    return os.path.join(graphs_dir, COMPANION_GRAPH_ID, COMPANION_NODE_ID)


def companion_node_config_path(graphs_dir: str) -> str:
    return os.path.join(companion_node_dir(graphs_dir), "config.json")
