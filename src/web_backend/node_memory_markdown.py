from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from .shared import envelope_text
from .shared import normalize_envelope


def render_memory_markdown_entry(record: dict[str, Any]) -> str:
    normalized = normalize_envelope(record, default_role=str(record.get("role") or "assistant"))
    message_id = _safe_markdown_comment_value(normalized.get("id") or "")
    created_at = _display_timestamp(normalized.get("created_at"))
    role = str(normalized.get("role") or "assistant").strip().lower() or "assistant"
    payload = envelope_text(normalized)
    return f"\n<!-- message_id: {message_id} -->\n**[{created_at}] {role}**: {payload}\n"


def render_memory_markdown(records: list[dict[str, Any]]) -> str:
    return "".join(render_memory_markdown_entry(record) for record in records if isinstance(record, dict))


def _display_timestamp(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if len(text) >= 19:
        return text[:19]
    return text


def _safe_markdown_comment_value(value: object) -> str:
    text = str(value or "").strip() or uuid.uuid4().hex
    return text.replace("--", "__").replace(">", "_")
