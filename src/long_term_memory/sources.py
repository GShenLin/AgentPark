from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.message_protocol import envelope_text
from src.web_backend.node_memory_store import load_recent_node_memory_records
from .contracts import Source, digest


def load_sources(node_dir: Path) -> list[Source]:
    """Read a transactionally consistent node history, including archived tool evidence."""
    records = load_recent_node_memory_records(
        str(node_dir / "memory.md"), str(node_dir / "messages.jsonl"), limit=None,
    )
    groups: dict[str, list[dict]] = {}
    legacy_turn = ""
    for record in records:
        role = record.get("role")
        if role not in {"user", "assistant", "assistant_progress", "tool", "function", "system"}:
            continue
        record_id = record["id"]
        if role == "user":
            legacy_turn = record_id
        trace_id = record.get("trace_id") or legacy_turn
        if not trace_id:
            continue
        groups.setdefault(trace_id, []).append({
            "id": record_id, "role": role, "created_at": record["created_at"],
            "text": envelope_text(record), "parts": record.get("parts", []),
        })
    result = []
    for trace, items in groups.items():
        updated = max(datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")).timestamp() for item in items)
        complete = any(item["role"] == "user" for item in items) and items[-1]["role"] == "assistant"
        result.append(Source(digest(trace), trace, updated, tuple(items), complete))
    return sorted(result, key=lambda source: (source.updated_at, source.id))
