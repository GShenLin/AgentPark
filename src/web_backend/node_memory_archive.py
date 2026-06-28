from __future__ import annotations

import os
from collections.abc import Callable

from src.file_transaction import append_text

from .node_memory_errors import NodeMemoryPersistenceFailure
from .node_memory_markdown import render_memory_markdown_entry
from .node_memory_paths import active_paths
from .node_memory_paths import archive_paths_for_date
from .node_memory_paths import node_memory_dir
from .node_memory_paths import record_date
from .node_memory_records import append_jsonl_record
from .node_memory_records import read_jsonl_records
from .node_memory_records import read_record_ids
from .node_memory_records import write_jsonl_records
from .node_memory_records import write_markdown_records


def enforce_active_memory_limit(
    memory_path: str,
    messages_path: str,
    failures: list[NodeMemoryPersistenceFailure],
    *,
    max_entries_reader: Callable[[], int],
) -> None:
    current = active_paths(node_memory_dir(memory_path, messages_path))
    active_messages_path = current.get("messages_path") or ""
    if not active_messages_path or not os.path.exists(active_messages_path):
        return
    max_entries = max_entries_reader()
    records = read_jsonl_records(active_messages_path)
    if len(records) <= max_entries:
        return

    node_dir = node_memory_dir(memory_path, messages_path)
    records_to_archive = records[:-max_entries]
    active_records = records[-max_entries:]
    archive_records(node_dir, records_to_archive, failures)
    if failures:
        return
    rewrite_active_records(current, active_records, failures)


def archive_records(
    node_dir: str,
    records: list[dict],
    failures: list[NodeMemoryPersistenceFailure],
) -> None:
    if not records:
        return
    if not node_dir:
        failures.append(NodeMemoryPersistenceFailure(target="archive", path="", error="node memory dir is empty"))
        return
    try:
        existing_ids_by_date: dict[str, set[str]] = {}
        for record in records:
            date_text = record_date(record)
            if date_text not in existing_ids_by_date:
                archive_messages = archive_paths_for_date(node_dir, date_text)["messages_path"]
                existing_ids_by_date[date_text] = read_record_ids(archive_messages)

            record_id = str(record.get("id") or "").strip()
            if record_id and record_id in existing_ids_by_date[date_text]:
                continue

            paths = archive_paths_for_date(node_dir, date_text)
            append_jsonl_record(paths["messages_path"], record)
            append_text(paths["memory_path"], render_memory_markdown_entry(record))
            if record_id:
                existing_ids_by_date[date_text].add(record_id)
    except Exception as exc:
        failures.append(
            NodeMemoryPersistenceFailure(
                target="archive",
                path=node_dir,
                error=f"{type(exc).__name__}: {exc}",
            )
        )


def rewrite_active_records(
    paths: dict[str, str],
    records: list[dict],
    failures: list[NodeMemoryPersistenceFailure],
) -> None:
    try:
        write_jsonl_records(paths.get("messages_path") or "", records)
    except Exception as exc:
        failures.append(
            NodeMemoryPersistenceFailure(
                target="messages",
                path=paths.get("messages_path") or "",
                error=f"{type(exc).__name__}: {exc}",
            )
        )
    try:
        write_markdown_records(paths.get("memory_path") or "", records)
    except Exception as exc:
        failures.append(
            NodeMemoryPersistenceFailure(
                target="memory",
                path=paths.get("memory_path") or "",
                error=f"{type(exc).__name__}: {exc}",
            )
        )
