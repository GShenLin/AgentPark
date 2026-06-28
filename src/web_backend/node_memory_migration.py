from __future__ import annotations

import os
from collections.abc import Callable

from src.file_transaction import replace_path

from .node_memory_archive import rewrite_active_records
from .node_memory_errors import NodeMemoryPersistenceFailure
from .node_memory_paths import active_paths
from .node_memory_paths import node_memory_dir
from .node_memory_records import read_jsonl_records


def migrate_legacy_node_memory(
    memory_path: str,
    messages_path: str,
    failures: list[NodeMemoryPersistenceFailure],
    *,
    enforce_active_memory_limit: Callable[[str, str, list[NodeMemoryPersistenceFailure]], None],
) -> None:
    node_dir = node_memory_dir(memory_path, messages_path)
    if not node_dir:
        return
    current = active_paths(node_dir)

    if memory_path and os.path.abspath(memory_path) != os.path.abspath(current["memory_path"]):
        move_legacy_markdown_to_active(memory_path, current["memory_path"], failures)

    if not messages_path or not os.path.exists(messages_path):
        return

    try:
        records = read_jsonl_records(messages_path)
        if os.path.abspath(messages_path) != os.path.abspath(current["messages_path"]):
            rewrite_active_records(current, records, failures)
            os.remove(messages_path)
        elif not os.path.exists(current["memory_path"]):
            rewrite_active_records(current, records, failures)
        if not failures:
            enforce_active_memory_limit(memory_path, messages_path, failures)
    except Exception as exc:
        failures.append(
            NodeMemoryPersistenceFailure(
                target="migration",
                path=messages_path,
                error=f"{type(exc).__name__}: {exc}",
            )
        )


def move_legacy_markdown_to_active(
    legacy_memory_path: str,
    active_memory_path: str,
    failures: list[NodeMemoryPersistenceFailure],
) -> None:
    if not legacy_memory_path or not os.path.exists(legacy_memory_path):
        return
    try:
        if os.path.getsize(legacy_memory_path) <= 0:
            os.remove(legacy_memory_path)
            return
        parent = os.path.dirname(active_memory_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if not os.path.exists(active_memory_path):
            replace_path(legacy_memory_path, active_memory_path)
    except Exception as exc:
        failures.append(
            NodeMemoryPersistenceFailure(
                target="migration",
                path=legacy_memory_path,
                error=f"{type(exc).__name__}: {exc}",
            )
        )
