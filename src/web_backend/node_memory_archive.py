from __future__ import annotations

import os
from collections.abc import Callable

from src.file_transaction import append_text

from .node_memory_errors import NodeMemoryPersistenceFailure
from .node_memory_active_state import ActiveMemoryState
from .node_memory_active_state import save_active_memory_state
from .node_memory_active_state import state_from_records
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
    active_state: ActiveMemoryState,
) -> None:
    current = active_paths(node_memory_dir(memory_path, messages_path))
    active_messages_path = current.get("messages_path") or ""
    if not active_messages_path or not os.path.exists(active_messages_path):
        return
    max_entries = max_entries_reader()
    if active_state.record_count <= max_entries:
        _save_active_state(active_messages_path, active_state, failures)
        return

    node_dir = node_memory_dir(memory_path, messages_path)
    archive_end = _archive_end_for_complete_turns(active_state, max_entries)
    if archive_end <= 0:
        _save_active_state(active_messages_path, active_state, failures)
        return
    records = read_jsonl_records(active_messages_path)
    if len(records) != active_state.record_count:
        failures.append(
            NodeMemoryPersistenceFailure(
                target="active_state",
                path=active_messages_path,
                error=(
                    "record count mismatch: "
                    f"state={active_state.record_count}, file={len(records)}"
                ),
            )
        )
        return
    records_to_archive = records[:archive_end]
    active_records = records[archive_end:]
    archive_records(node_dir, records_to_archive, failures)
    if failures:
        return
    rewrite_active_records(current, active_records, failures)
    if failures:
        return
    _save_active_state(
        active_messages_path,
        state_from_records(active_records, active_messages_path),
        failures,
    )


def _archive_end_for_complete_turns(state: ActiveMemoryState, max_entries: int) -> int:
    """Choose an archive boundary without splitting the newest user turn.

    The configured limit remains exact whenever a user-turn boundary can
    satisfy it. A single in-flight turn may temporarily exceed the limit; it
    is archived as a unit when the next user turn starts. This avoids parsing
    and rewriting every large tool result while a node is still working.
    """
    overflow = state.record_count - max(1, int(max_entries))
    if overflow <= 0:
        return 0

    user_starts = state.user_starts
    if not user_starts:
        return overflow

    for index in user_starts:
        if index > 0 and index >= overflow:
            return index

    latest_turn_start = user_starts[-1]
    return latest_turn_start if latest_turn_start > 0 else 0


def _save_active_state(
    messages_path: str,
    state: ActiveMemoryState,
    failures: list[NodeMemoryPersistenceFailure],
) -> None:
    try:
        save_active_memory_state(messages_path, state)
    except Exception as exc:
        failures.append(
            NodeMemoryPersistenceFailure(
                target="active_state",
                path=messages_path,
                error=f"{type(exc).__name__}: {exc}",
            )
        )


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
