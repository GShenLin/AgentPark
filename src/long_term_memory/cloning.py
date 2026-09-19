"""Copy durable memories to a new owner without inheriting worker execution state."""
from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from pathlib import Path


def clone_memory(
    source_dir: str, target_dir: str, source_graph: str, target_graph: str,
    source_node: str, target_node: str,
) -> None:
    if not all((source_graph, target_graph, source_node, target_node)):
        raise ValueError("memory identity requires graph and node IDs")
    source = Path(source_dir) / "long_term_memory"
    target = Path(target_dir) / "long_term_memory"
    if source.is_symlink():
        raise ValueError("memory root cannot be a symlink")
    path = source / "state.sqlite3"
    if not path.exists():
        return
    # Block publication and pruning while copying the database and its active files.
    # Backup uses a separate reader: backing up a write transaction would block.
    with closing(sqlite3.connect(path, timeout=30)) as guard:
        try:
            guard.execute("BEGIN IMMEDIATE")
            owner = guard.execute("SELECT graph_id,node_id,schema_version,publication FROM owner").fetchone()
            if owner is None or owner[:3] != (source_graph, source_node, 1):
                raise ValueError("memory owner or schema does not match the node being copied")
            target.mkdir(parents=True, exist_ok=False)
            with closing(sqlite3.connect(path, timeout=30)) as reader:
                with closing(sqlite3.connect(target / "state.sqlite3", timeout=30)) as copied:
                    reader.backup(copied)
                    with copied:
                        copied.execute("UPDATE owner SET graph_id=?,node_id=?,revision=revision+1",
                                       (target_graph, target_node))
                        copied.execute("DELETE FROM jobs")
                        copied.execute("DELETE FROM runs")
            if owner[3] is not None:
                folder = source / "generations" / owner[3]
                if folder.is_symlink() or not folder.resolve().is_relative_to((source / "generations").resolve()):
                    raise ValueError("memory publication escapes its generations directory")
                shutil.copytree(folder, target / "generations" / owner[3])
        finally:
            guard.rollback()
