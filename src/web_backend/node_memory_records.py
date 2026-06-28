from __future__ import annotations

import json
import os
import uuid
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


def read_jsonl_records_reversed(path: str) -> list[dict[str, Any]]:
    if not path or not os.path.exists(path):
        return []
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.readlines()
        for offset, line in enumerate(reversed(lines)):
            line_number = len(lines) - offset
            record = parse_record_line(line, line_number=line_number)
            if record is not None:
                records.append(record)
    return records


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
