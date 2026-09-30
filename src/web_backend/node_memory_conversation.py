"""Lightweight conversation projection and explicit, per-turn detail reads.

File indexes retain record locations and dialogue bodies, never tool/metadata
payloads. They are keyed by the file identity so append, rotation, deletion and
restore invalidate them. Callers hold the normal node-memory transaction lock.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache

from .node_memory_paths import active_paths, iter_archive_date_dirs, node_memory_dir
from .node_memory_records import parse_record_line


USER_ROLES = {"user", "human"}
FINAL_ROLES = {"assistant", "agent", "system"}


@dataclass(frozen=True)
class RecordLocation:
    path: str
    offset: int
    length: int
    role: str
    record_id: str
    digest: str
    tool_count: int
    body: dict | None


@lru_cache(maxsize=128)
def _file_index(path: str, size: int, mtime_ns: int, ctime_ns: int) -> tuple[RecordLocation, ...]:
    records = []
    with open(path, "rb") as handle:
        line_number = 0
        while handle.tell() < size:
            offset = handle.tell()
            raw = handle.readline(size - offset)
            line_number += 1
            record = parse_record_line(raw.decode("utf-8"), line_number=line_number)
            if record is None:
                continue
            role = record["role"]
            records.append(RecordLocation(
                path, offset, len(raw), role, record["id"], hashlib.sha256(raw).hexdigest(),
                sum(1 for part in record["parts"] if part.get("type") == "tool_call"),
                record if role in USER_ROLES | FINAL_ROLES else None,
            ))
    return tuple(records)


def _locations(memory_path: str, messages_path: str) -> list[RecordLocation]:
    node_dir = node_memory_dir(memory_path, messages_path)
    paths = [os.path.join(directory, "messages.jsonl")
             for directory in iter_archive_date_dirs(node_dir, reverse=False)]
    paths.append(active_paths(node_dir)["messages_path"])
    result = []
    for path in paths:
        try:
            stat = os.stat(path)
        except FileNotFoundError:
            continue
        result.extend(_file_index(path, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
    return result


def _read_records(locations: list[RecordLocation]) -> list[dict]:
    result = []
    # A turn can span archive files. Open only files containing this turn.
    handles = {}
    try:
        for location in locations:
            if location.body is not None:
                result.append(location.body)
                continue
            if location.path not in handles:
                handles[location.path] = open(location.path, "rb")
            handle = handles[location.path]
            handle.seek(location.offset)
            record = parse_record_line(handle.read(location.length).decode("utf-8"), line_number=0)
            if record is None:
                raise ValueError(f"Indexed memory record is empty: {location.path}:{location.offset}")
            result.append(record)
    finally:
        for handle in handles.values():
            handle.close()
    return result


def read_conversation(
    memory_path: str, messages_path: str, *, running: bool, turn_id: str = "",
) -> list[dict]:
    locations = _locations(memory_path, messages_path)
    turns: list[list[RecordLocation]] = []
    preamble = []
    for location in locations:
        if location.role in USER_ROLES:
            turns.append([location])
        elif turns:
            turns[-1].append(location)
        elif location.body is not None:
            preamble.append(location.body)

    if turn_id:
        for turn in turns:
            if turn[0].record_id == turn_id:
                return _read_records(turn)
        raise KeyError(turn_id)

    output = list(preamble)
    for index, turn in enumerate(turns):
        final_index = next((i for i in range(len(turn) - 1, 0, -1)
                            if turn[i].role in FINAL_ROLES), None)
        progress = turn[1:final_index] if final_index is not None else turn[1:]
        active = running and index == len(turns) - 1
        # All turns use the same lazy detail contract, including the active turn.
        visible = [turn[0]] + ([turn[final_index]] if final_index is not None else [])
        messages = _read_records(visible)
        summary = {
            "turn_id": turn[0].record_id,
            "revision": hashlib.sha256("".join(item.digest for item in turn).encode("ascii")).hexdigest(),
            "running": active,
            "item_count": len(progress),
            "tool_count": sum(item.tool_count for item in progress),
            "has_metadata": any(item.role == "metadata" for item in turn),
        }
        messages[0] = {**messages[0], "turn_summary": summary}
        output.extend(messages)
    return output
