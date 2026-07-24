from __future__ import annotations

import json
import os
from dataclasses import dataclass

from src.file_transaction import atomic_write_text

from .node_memory_records import read_jsonl_records


ACTIVE_MEMORY_STATE_FILENAME = ".active-memory-state.json"
ACTIVE_MEMORY_STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ActiveMemoryState:
    record_count: int
    user_starts: tuple[int, ...]
    messages_size: int
    messages_mtime_ns: int


def load_active_memory_state(messages_path: str) -> ActiveMemoryState:
    file_size, mtime_ns = _messages_stat(messages_path)
    if file_size == 0:
        return ActiveMemoryState(0, (), file_size, mtime_ns)

    state_path = active_memory_state_path(messages_path)
    if os.path.isfile(state_path):
        payload = _read_state_payload(state_path)
        state = _state_from_payload(payload, state_path)
        if state.messages_size == file_size and state.messages_mtime_ns == mtime_ns:
            return state

    records = read_jsonl_records(messages_path)
    return state_from_records(records, messages_path)


def load_committed_active_memory_state(messages_path: str) -> ActiveMemoryState | None:
    """Read the last durable complete-record boundary for lock-free readers."""
    state_path = active_memory_state_path(messages_path)
    if not os.path.isfile(state_path):
        return None
    return _state_from_payload(_read_state_payload(state_path), state_path)


def advance_active_memory_state(
    state: ActiveMemoryState,
    record: dict,
    messages_path: str,
) -> ActiveMemoryState:
    next_index = state.record_count
    role = str(record.get("role") or "").strip().lower()
    user_starts = state.user_starts + ((next_index,) if role in {"user", "human"} else ())
    file_size, mtime_ns = _messages_stat(messages_path)
    return ActiveMemoryState(next_index + 1, user_starts, file_size, mtime_ns)


def state_from_records(records: list[dict], messages_path: str) -> ActiveMemoryState:
    file_size, mtime_ns = _messages_stat(messages_path)
    return ActiveMemoryState(
        record_count=len(records),
        user_starts=tuple(
            index
            for index, record in enumerate(records)
            if str(record.get("role") or "").strip().lower() in {"user", "human"}
        ),
        messages_size=file_size,
        messages_mtime_ns=mtime_ns,
    )


def save_active_memory_state(messages_path: str, state: ActiveMemoryState) -> None:
    payload = {
        "schema_version": ACTIVE_MEMORY_STATE_SCHEMA_VERSION,
        "record_count": state.record_count,
        "user_starts": list(state.user_starts),
        "messages_size": state.messages_size,
        "messages_mtime_ns": state.messages_mtime_ns,
    }
    atomic_write_text(
        active_memory_state_path(messages_path),
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
    )


def active_memory_state_path(messages_path: str) -> str:
    parent = os.path.dirname(os.path.abspath(str(messages_path or "").strip()))
    return os.path.join(parent, ACTIVE_MEMORY_STATE_FILENAME)


def _messages_stat(messages_path: str) -> tuple[int, int]:
    try:
        stat = os.stat(messages_path)
    except FileNotFoundError:
        return 0, 0
    return int(stat.st_size), int(stat.st_mtime_ns)


def _read_state_payload(state_path: str) -> dict:
    with open(state_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"active memory state must be a JSON object: {state_path}")
    return payload


def _state_from_payload(payload: dict, state_path: str) -> ActiveMemoryState:
    if payload.get("schema_version") != ACTIVE_MEMORY_STATE_SCHEMA_VERSION:
        raise ValueError(f"unsupported active memory state schema: {state_path}")
    record_count = payload.get("record_count")
    messages_size = payload.get("messages_size")
    messages_mtime_ns = payload.get("messages_mtime_ns")
    user_starts = payload.get("user_starts")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (record_count, messages_size, messages_mtime_ns)):
        raise ValueError(f"active memory state counters must be non-negative integers: {state_path}")
    if not isinstance(user_starts, list) or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0 or value >= record_count
        for value in user_starts
    ):
        raise ValueError(f"active memory state user_starts is invalid: {state_path}")
    if user_starts != sorted(set(user_starts)):
        raise ValueError(f"active memory state user_starts must be unique and ordered: {state_path}")
    return ActiveMemoryState(record_count, tuple(user_starts), messages_size, messages_mtime_ns)


__all__ = [
    "ACTIVE_MEMORY_STATE_FILENAME",
    "ActiveMemoryState",
    "active_memory_state_path",
    "advance_active_memory_state",
    "load_committed_active_memory_state",
    "load_active_memory_state",
    "save_active_memory_state",
    "state_from_records",
]
