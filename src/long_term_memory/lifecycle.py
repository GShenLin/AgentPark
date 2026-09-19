"""Node identity and maintenance operations; never share a store between nodes."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .store import invalidate_node_memory


def require_memory_idle(node_dir: str) -> None:
    path = Path(node_dir) / "long_term_memory" / "state.sqlite3"
    if not path.exists():
        return
    db = sqlite3.connect(path, timeout=30)
    try:
        if db.execute("SELECT 1 FROM jobs WHERE lease_until>?", (time.time(),)).fetchone():
            raise ValueError("node memory consolidation is running; move the node after it completes")
    finally:
        db.close()


def rebind_memory(
    node_dir: str, source_graph: str, target_graph: str, source_node: str, target_node: str,
) -> None:
    """Transfer an idle database from its verified old identity to its new identity."""
    if not all((source_graph, target_graph, source_node, target_node)):
        raise ValueError("memory identity requires graph and node IDs")
    path = Path(node_dir) / "long_term_memory" / "state.sqlite3"
    if not path.exists():
        return
    db = sqlite3.connect(path, timeout=30)
    try:
        with db:
            db.execute("BEGIN IMMEDIATE")
            owner = db.execute("SELECT graph_id,node_id,schema_version FROM owner").fetchone()
            if owner == (target_graph, target_node, 1):
                return
            if owner != (source_graph, source_node, 1):
                raise ValueError("memory owner does not match the node being moved")
            if db.execute("SELECT 1 FROM jobs WHERE lease_until>?", (time.time(),)).fetchone():
                raise ValueError("node memory consolidation is running; change identity after it completes")
            db.execute("UPDATE owner SET graph_id=?,node_id=?,revision=revision+1", (target_graph, target_node))
    finally:
        db.close()


def clear_derived_memories(memories_root: str) -> dict:
    root = Path(memories_root).resolve()
    count = 0
    for path in root.glob("*/*/long_term_memory/state.sqlite3"):
        if not path.resolve().is_relative_to(root):
            raise ValueError("memory database is outside the configured memories root")
        invalidate_node_memory(str(path.parent.parent), reset=True)
        count += 1
    return {"ok": True, "cleared_nodes": count, "stdout": f"Cleared long-term memory for {count} nodes. Original histories retained."}
