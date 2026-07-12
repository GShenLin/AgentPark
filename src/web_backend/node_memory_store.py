from __future__ import annotations

import os
from typing import Any

from src.file_transaction import KeyedTransactionQueue
from src.file_transaction import append_text
from src.file_transaction import atomic_write_text
from src.file_transaction import run_with_interprocess_lock
from src.file_transaction import touch_file

from .node_memory_archive import enforce_active_memory_limit as _enforce_active_memory_limit_impl
from .node_memory_errors import NodeMemoryPersistenceError
from .node_memory_errors import NodeMemoryPersistenceFailure
from .node_memory_errors import raise_if_failures as _raise_if_failures
from .node_memory_limits import read_max_active_memory_entries as _read_max_active_memory_entries
from .node_memory_markdown import render_memory_markdown_entry
from .node_memory_paths import MEMORY_FILENAME
from .node_memory_paths import MESSAGES_FILENAME
from .node_memory_paths import active_paths as _active_paths
from .node_memory_paths import iter_archive_date_dirs as _iter_archive_date_dirs
from .node_memory_paths import node_memory_dir as _node_memory_dir
from .node_memory_records import append_jsonl_record as _append_jsonl_record
from .node_memory_records import build_node_memory_record
from .node_memory_records import read_jsonl_records as _read_jsonl_records
from .node_memory_records import read_jsonl_records_reversed as _read_jsonl_records_reversed
from .node_memory_records import write_jsonl_records as _write_jsonl_records
from .node_memory_records import write_markdown_records as _write_markdown_records
from .node_tool_history import build_tool_call_history_envelope
from .shared import envelope_text


_NODE_MEMORY_QUEUE = KeyedTransactionQueue()

__all__ = [
    "NodeMemoryPersistenceError",
    "NodeMemoryPersistenceFailure",
    "append_node_memory_entry",
    "append_node_memory_entry_once",
    "append_node_tool_call_entry",
    "build_node_memory_record",
    "clear_node_memory",
    "current_node_memory_paths",
    "delete_node_memory_record",
    "ensure_node_memory_files",
    "load_recent_node_memory_records",
    "load_latest_node_memory_turn",
    "node_memory_paths_for_record",
    "read_node_memory_text",
    "wait_for_node_memory_idle",
]


def ensure_node_memory_files(memory_path: str, messages_path: str) -> None:
    return _run_node_memory_transaction(
        memory_path,
        messages_path,
        lambda: _ensure_node_memory_files_unlocked(memory_path, messages_path),
    )


def _ensure_node_memory_files_unlocked(memory_path: str, messages_path: str) -> None:
    failures: list[NodeMemoryPersistenceFailure] = []
    current = current_node_memory_paths(memory_path, messages_path)
    for target, path in (("memory", current["memory_path"]), ("messages", current["messages_path"])):
        if not path:
            failures.append(NodeMemoryPersistenceFailure(target=target, path="", error="path is empty"))
            continue
        try:
            _touch_file(path)
        except Exception as exc:
            failures.append(
                NodeMemoryPersistenceFailure(target=target, path=path, error=f"{type(exc).__name__}: {exc}")
            )
    _raise_if_failures(failures)


def append_node_memory_entry(memory_path: str, messages_path: str, role: str, message: object) -> None:
    record = build_node_memory_record(role, message)
    payload = envelope_text(record)
    if not payload and not (record.get("parts") or []):
        return

    return _run_node_memory_transaction(
        memory_path,
        messages_path,
        lambda: _append_node_memory_record_unlocked(memory_path, messages_path, record),
    )


def append_node_memory_entry_once(memory_path: str, messages_path: str, role: str, message: object) -> bool:
    record = build_node_memory_record(role, message)
    record_id = str(record.get("id") or "").strip()
    payload = envelope_text(record)
    if not record_id or (not payload and not (record.get("parts") or [])):
        return False

    def append_if_missing() -> bool:
        paths = current_node_memory_paths(memory_path, messages_path)
        messages_file = paths.get("messages_path") or ""
        if messages_file and os.path.exists(messages_file):
            try:
                for existing in _read_jsonl_records(messages_file):
                    if str(existing.get("id") or "").strip() == record_id:
                        return False
            except Exception:
                pass
        _append_node_memory_record_unlocked(memory_path, messages_path, record)
        return True

    return _run_node_memory_transaction(memory_path, messages_path, append_if_missing)


def _append_node_memory_record_unlocked(memory_path: str, messages_path: str, record: dict[str, Any]) -> None:
    failures: list[NodeMemoryPersistenceFailure] = []
    paths = current_node_memory_paths(memory_path, messages_path)
    _append_messages_record(paths["messages_path"], record, failures)
    _append_markdown_record(paths["memory_path"], record, failures)
    if not failures:
        _enforce_active_memory_limit(memory_path, messages_path, failures)
    _raise_if_failures(failures)


def append_node_tool_call_entry(memory_path: str, messages_path: str, event: dict[str, Any]) -> None:
    if not isinstance(event, dict):
        return
    append_node_memory_entry(memory_path, messages_path, "tool", build_tool_call_history_envelope(event))


def clear_node_memory(memory_path: str, messages_path: str) -> int:
    return _run_node_memory_transaction(
        memory_path,
        messages_path,
        lambda: _clear_node_memory_unlocked(memory_path, messages_path),
    )


def _clear_node_memory_unlocked(memory_path: str, messages_path: str) -> int:
    failures: list[NodeMemoryPersistenceFailure] = []
    node_dir = _node_memory_dir(memory_path, messages_path)
    if not node_dir:
        failures.append(NodeMemoryPersistenceFailure(target="memory", path="", error="node memory dir is empty"))
        _raise_if_failures(failures)
        return 0

    paths_to_clear: set[str] = set()
    for date_dir in _iter_archive_date_dirs(node_dir, reverse=False):
        paths_to_clear.add(os.path.join(date_dir, MEMORY_FILENAME))
        paths_to_clear.add(os.path.join(date_dir, MESSAGES_FILENAME))

    current = current_node_memory_paths(memory_path, messages_path)
    paths_to_clear.add(current["memory_path"])
    paths_to_clear.add(current["messages_path"])

    cleared = 0
    for target_path in sorted(path for path in paths_to_clear if path):
        try:
            parent = os.path.dirname(target_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            atomic_write_text(target_path, "")
            cleared += 1
        except Exception as exc:
            failures.append(
                NodeMemoryPersistenceFailure(
                    target="clear",
                    path=target_path,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    _raise_if_failures(failures)
    return cleared


def delete_node_memory_record(memory_path: str, messages_path: str, message_id: str) -> dict[str, Any]:
    target_id = str(message_id or "").strip()
    if not target_id:
        return {"deleted": 0}
    return _run_node_memory_transaction(
        memory_path,
        messages_path,
        lambda: _delete_node_memory_record_unlocked(memory_path, messages_path, target_id),
    )


def _delete_node_memory_record_unlocked(memory_path: str, messages_path: str, message_id: str) -> dict[str, Any]:
    failures: list[NodeMemoryPersistenceFailure] = []
    node_dir = _node_memory_dir(memory_path, messages_path)
    if not node_dir:
        failures.append(NodeMemoryPersistenceFailure(target="memory", path="", error="node memory dir is empty"))
        _raise_if_failures(failures)
        return {"deleted": 0}

    deleted = 0
    record_paths: list[dict[str, str]] = []
    for date_dir in _iter_archive_date_dirs(node_dir, reverse=False):
        record_paths.append(
            {
                "memory_path": os.path.join(date_dir, MEMORY_FILENAME),
                "messages_path": os.path.join(date_dir, MESSAGES_FILENAME),
            }
        )
    record_paths.append(current_node_memory_paths(memory_path, messages_path))

    seen_messages_paths: set[str] = set()
    for paths in record_paths:
        messages_file = paths.get("messages_path") or ""
        if not messages_file or messages_file in seen_messages_paths or not os.path.exists(messages_file):
            continue
        seen_messages_paths.add(messages_file)
        try:
            records = _read_jsonl_records(messages_file)
        except Exception as exc:
            failures.append(
                NodeMemoryPersistenceFailure(
                    target="messages",
                    path=messages_file,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        next_records = [record for record in records if str(record.get("id") or "").strip() != message_id]
        removed = len(records) - len(next_records)
        if removed <= 0:
            continue
        try:
            _write_jsonl_records(messages_file, next_records)
            _write_markdown_records(paths.get("memory_path") or "", next_records)
            deleted += removed
        except Exception as exc:
            failures.append(
                NodeMemoryPersistenceFailure(
                    target="delete",
                    path=messages_file,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    _raise_if_failures(failures)
    return {"deleted": deleted}


def current_node_memory_paths(memory_path: str, messages_path: str) -> dict[str, str]:
    return _active_paths(_node_memory_dir(memory_path, messages_path))


def node_memory_paths_for_record(memory_path: str, messages_path: str, record: dict[str, Any]) -> dict[str, str]:
    return current_node_memory_paths(memory_path, messages_path)


def read_node_memory_text(memory_path: str, messages_path: str, *, max_chars: int | None = 20000) -> str:
    return _run_node_memory_transaction(
        memory_path,
        messages_path,
        lambda: _read_node_memory_text_unlocked(memory_path, messages_path, max_chars=max_chars),
    )


def _read_node_memory_text_unlocked(memory_path: str, messages_path: str, *, max_chars: int | None = 20000) -> str:
    failures: list[NodeMemoryPersistenceFailure] = []
    if max_chars is None:
        limit = None
    else:
        try:
            limit = int(max_chars)
        except Exception:
            limit = 20000
        if limit <= 0:
            return ""

    chunks: list[str] = []
    node_dir = _node_memory_dir(memory_path, messages_path)
    for date_dir in _iter_archive_date_dirs(node_dir, reverse=False):
        path = os.path.join(date_dir, MEMORY_FILENAME)
        if not os.path.exists(path):
            continue
        try:
            text = _read_text(path)
        except Exception as exc:
            failures.append(
                NodeMemoryPersistenceFailure(
                    target="memory",
                    path=path,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        if not text:
            continue
        chunks.append(text)

    current = current_node_memory_paths(memory_path, messages_path)
    current_memory_path = current.get("memory_path") or ""
    if current_memory_path and os.path.exists(current_memory_path):
        try:
            chunks.append(_read_text(current_memory_path))
        except Exception as exc:
            failures.append(
                NodeMemoryPersistenceFailure(
                    target="memory",
                    path=current_memory_path,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    _raise_if_failures(failures)
    text = "".join(chunks)
    if limit is None:
        return text
    return text[-limit:]


def load_recent_node_memory_records(
    memory_path: str,
    messages_path: str,
    *,
    limit: int | None,
    roles: set[str] | None = None,
) -> list[dict[str, Any]]:
    normalized_roles = {str(role or "").strip().lower() for role in roles} if roles is not None else None
    return _run_node_memory_transaction(
        memory_path,
        messages_path,
        lambda: _load_recent_node_memory_records_unlocked(
            memory_path,
            messages_path,
            limit=limit,
            roles=normalized_roles,
        ),
    )


def load_latest_node_memory_turn(
    memory_path: str,
    messages_path: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Load the newest user turn and report whether it is the complete history."""
    return _run_node_memory_transaction(
        memory_path,
        messages_path,
        lambda: _load_latest_node_memory_turn_unlocked(memory_path, messages_path),
    )


def _load_latest_node_memory_turn_unlocked(
    memory_path: str,
    messages_path: str,
) -> tuple[list[dict[str, Any]], bool]:
    failures: list[NodeMemoryPersistenceFailure] = []
    output_reversed: list[dict[str, Any]] = []
    found_user = False

    current = current_node_memory_paths(memory_path, messages_path)
    paths: list[str] = []
    current_messages_path = current.get("messages_path") or ""
    if current_messages_path and os.path.exists(current_messages_path):
        paths.append(current_messages_path)
    for date_dir in _iter_archive_date_dirs(_node_memory_dir(memory_path, messages_path), reverse=True):
        path = os.path.join(date_dir, MESSAGES_FILENAME)
        if os.path.exists(path):
            paths.append(path)

    for path in paths:
        try:
            for record in _read_jsonl_records_reversed(path):
                if found_user:
                    return list(reversed(output_reversed)), False
                output_reversed.append(record)
                role = str(record.get("role") or "").strip().lower()
                if role in {"user", "human"}:
                    found_user = True
        except Exception as exc:
            failures.append(
                NodeMemoryPersistenceFailure(
                    target="messages",
                    path=path,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    _raise_if_failures(failures)
    if not found_user:
        return list(reversed(output_reversed)), True
    return list(reversed(output_reversed)), True


def _load_recent_node_memory_records_unlocked(
    memory_path: str,
    messages_path: str,
    *,
    limit: int | None,
    roles: set[str] | None,
) -> list[dict[str, Any]]:
    failures: list[NodeMemoryPersistenceFailure] = []

    if limit is None:
        remaining = None
    else:
        try:
            remaining = int(limit)
        except Exception:
            remaining = 0
        if remaining <= 0:
            return []

    output_reversed: list[dict[str, Any]] = []
    current = current_node_memory_paths(memory_path, messages_path)
    current_messages_path = current.get("messages_path") or ""
    if current_messages_path and os.path.exists(current_messages_path):
        try:
            for record in _read_jsonl_records_reversed(current_messages_path):
                if roles is not None and str(record.get("role") or "").strip().lower() not in roles:
                    continue
                output_reversed.append(record)
                if remaining is not None:
                    remaining -= 1
                if remaining is not None and remaining <= 0:
                    return list(reversed(output_reversed))
        except Exception as exc:
            failures.append(
                NodeMemoryPersistenceFailure(
                    target="messages",
                    path=current_messages_path,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    for date_dir in _iter_archive_date_dirs(_node_memory_dir(memory_path, messages_path), reverse=True):
        path = os.path.join(date_dir, MESSAGES_FILENAME)
        if not os.path.exists(path):
            continue
        try:
            for record in _read_jsonl_records_reversed(path):
                if roles is not None and str(record.get("role") or "").strip().lower() not in roles:
                    continue
                output_reversed.append(record)
                if remaining is not None:
                    remaining -= 1
                if remaining is not None and remaining <= 0:
                    return list(reversed(output_reversed))
        except Exception as exc:
            failures.append(
                NodeMemoryPersistenceFailure(
                    target="messages",
                    path=path,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
    _raise_if_failures(failures)
    return list(reversed(output_reversed))


def wait_for_node_memory_idle(memory_path: str, messages_path: str) -> None:
    node_dir = _node_memory_dir(memory_path, messages_path)
    if node_dir:
        _NODE_MEMORY_QUEUE.wait_empty(node_dir)


def _append_messages_record(
    messages_path: str,
    record: dict[str, Any],
    failures: list[NodeMemoryPersistenceFailure],
) -> None:
    if not messages_path:
        failures.append(NodeMemoryPersistenceFailure(target="messages", path="", error="path is empty"))
        return
    try:
        _append_jsonl_record(messages_path, record)
    except Exception as exc:
        failures.append(
            NodeMemoryPersistenceFailure(
                target="messages",
                path=messages_path,
                error=f"{type(exc).__name__}: {exc}",
            )
        )


def _append_markdown_record(
    memory_path: str,
    record: dict[str, Any],
    failures: list[NodeMemoryPersistenceFailure],
) -> None:
    if not memory_path:
        failures.append(NodeMemoryPersistenceFailure(target="memory", path="", error="path is empty"))
        return
    try:
        append_text(memory_path, render_memory_markdown_entry(record))
    except Exception as exc:
        failures.append(
            NodeMemoryPersistenceFailure(
                target="memory",
                path=memory_path,
                error=f"{type(exc).__name__}: {exc}",
            )
        )


def _enforce_active_memory_limit(
    memory_path: str,
    messages_path: str,
    failures: list[NodeMemoryPersistenceFailure],
) -> None:
    _enforce_active_memory_limit_impl(
        memory_path,
        messages_path,
        failures,
        max_entries_reader=_read_max_active_memory_entries,
    )


def _touch_file(path: str) -> None:
    touch_file(path)


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _run_node_memory_transaction(memory_path: str, messages_path: str, func):
    node_dir = _node_memory_dir(memory_path, messages_path)
    if not node_dir:
        return func()
    lock_path = os.path.join(node_dir, ".node-memory.lock")
    return _NODE_MEMORY_QUEUE.run(node_dir, lambda: run_with_interprocess_lock(lock_path, func))
