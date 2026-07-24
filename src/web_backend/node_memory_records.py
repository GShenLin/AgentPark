from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterator
from typing import Any

from src.file_transaction import append_text
from src.file_transaction import atomic_write_text

from .node_memory_markdown import render_memory_markdown_entry
from .shared import normalize_envelope
from .shared import now_text


def build_node_memory_record(role: str, message: object) -> dict[str, Any]:
    envelope = normalize_envelope(message, default_role=role or "assistant")
    record = {
        "id": str(envelope.get("id") or uuid.uuid4().hex),
        "role": str(role or envelope.get("role") or "assistant").strip().lower() or "assistant",
        "parts": envelope.get("parts") if isinstance(envelope.get("parts"), list) else [],
        "created_at": str(envelope.get("created_at") or now_text()),
    }
    trace_id = str(envelope.get("trace_id") or "").strip()
    if trace_id:
        record["trace_id"] = trace_id
    return record


def append_jsonl_record(path: str, record: dict[str, Any]) -> None:
    append_text(path, json.dumps(record, ensure_ascii=False) + "\n")


def write_jsonl_records(path: str, records: list[dict[str, Any]]) -> None:
    if not path:
        raise ValueError("path is empty")
    atomic_write_text(path, "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records))


def write_markdown_records(path: str, records: list[dict[str, Any]]) -> None:
    if not path:
        raise ValueError("path is empty")
    atomic_write_text(path, "".join(render_memory_markdown_entry(record) for record in records))


def read_jsonl_records(path: str) -> list[dict[str, Any]]:
    if not path or not os.path.exists(path):
        return []
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            record = parse_record_line(line, line_number=line_number)
            if record is not None:
                records.append(record)
    return records


_JSON_ROLE_PATTERN = re.compile(rb'"role"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"')


def read_jsonl_records_reversed(
    path: str,
    *,
    materialize_roles: set[str] | None = None,
    chunk_size: int = 64 * 1024,
    max_bytes: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield JSONL records from newest to oldest without loading the file.

    Roles outside ``materialize_roles`` are represented by a lightweight
    placeholder. This lets latest-turn views skip multi-megabyte metadata
    records without decoding and allocating their nested payloads.
    """
    if not path or not os.path.exists(path):
        return
    normalized_roles = (
        {str(role or "").strip().lower() for role in materialize_roles}
        if materialize_roles is not None
        else None
    )
    safe_chunk_size = max(4096, int(chunk_size or 0))
    reverse_index = 0
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        if max_bytes is not None:
            position = min(position, max(0, int(max_bytes)))
        remainder = b""
        while position > 0:
            read_size = min(safe_chunk_size, position)
            position -= read_size
            handle.seek(position)
            data = handle.read(read_size) + remainder
            lines = data.split(b"\n")
            remainder = lines[0]
            for raw_line in reversed(lines[1:]):
                reverse_index += 1
                record = _parse_reversed_record_bytes(
                    raw_line,
                    reverse_index=reverse_index,
                    materialize_roles=normalized_roles,
                )
                if record is not None:
                    yield record
        if remainder.strip():
            reverse_index += 1
            record = _parse_reversed_record_bytes(
                remainder,
                reverse_index=reverse_index,
                materialize_roles=normalized_roles,
            )
            if record is not None:
                yield record


def _parse_reversed_record_bytes(
    raw_line: bytes,
    *,
    reverse_index: int,
    materialize_roles: set[str] | None,
) -> dict[str, Any] | None:
    raw = raw_line.strip()
    if not raw:
        return None
    role = _sniff_json_role(raw)
    if materialize_roles is not None and role and role not in materialize_roles:
        return {"id": "", "role": role, "parts": [], "created_at": "", "_deferred": True}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"invalid UTF-8 JSONL record at reverse index {reverse_index}: {exc}") from exc
    return parse_record_line(text, line_number=-reverse_index)


def _sniff_json_role(raw: bytes) -> str:
    match = _JSON_ROLE_PATTERN.search(raw)
    if match is None:
        return ""
    try:
        decoded = json.loads(b'"' + match.group(1) + b'"')
    except Exception:
        return ""
    return str(decoded or "").strip().lower()


def parse_record_line(line: str, *, line_number: int) -> dict[str, Any] | None:
    raw = str(line or "").strip()
    if not raw:
        return None
    try:
        item = json.loads(raw)
    except Exception as exc:
        raise ValueError(f"invalid JSONL record at line {line_number}: {exc}") from exc
    if not isinstance(item, dict):
        raise ValueError(f"JSONL record at line {line_number} must be an object")
    return build_node_memory_record(str(item.get("role") or "assistant"), item)


def read_record_ids(path: str) -> set[str]:
    ids: set[str] = set()
    for record in read_jsonl_records(path):
        record_id = str(record.get("id") or "").strip()
        if record_id:
            ids.add(record_id)
    return ids
