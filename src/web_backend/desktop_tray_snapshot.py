"""Read tray projections from canonical node configuration and commit metadata."""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictStr

from .node_config_errors import NodeConfigNotFoundError
from .node_config_service import node_config_service
from .node_conversation_activity import read_conversation_commit


class TrayNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    graph_id: StrictStr
    node_id: StrictStr
    name: StrictStr
    state: Literal["idle", "working", "stop"]
    saved_at_ns: int | None


class TraySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recent: list[TrayNode]
    working: list[TrayNode]


def build_tray_snapshot(graphs_root: Path) -> TraySnapshot:
    nodes: list[TrayNode] = []
    # Enumerate node configs, never infer activity from arbitrary file mtimes.
    for config_path in sorted(graphs_root.glob("*/*/config.json")):
        if config_path.parent.name == "agents":
            continue
        try:
            persistent = node_config_service.read_persistent_strict(str(config_path))
            config = node_config_service.with_runtime_fields(str(config_path), persistent, {"state"})
        except NodeConfigNotFoundError:
            continue  # A node can be deleted between enumeration and reading.
        nodes.append(TrayNode(
            graph_id=config_path.parent.parent.name,
            node_id=config["node_id"],
            name=config.get("name") or config["node_id"],
            state=config["state"],
            saved_at_ns=read_conversation_commit(config_path.parent),
        ))
    recent = sorted((node for node in nodes if node.saved_at_ns is not None),
                    key=lambda node: node.saved_at_ns, reverse=True)[:10]
    working = sorted((node for node in nodes if node.state == "working"),
                     key=lambda node: (node.graph_id, node.name, node.node_id))
    return TraySnapshot(recent=recent, working=working)
