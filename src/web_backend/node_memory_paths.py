from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any


ARCHIVE_DIRNAME = "archive"
MESSAGES_FILENAME = "messages.jsonl"
MEMORY_FILENAME = "memory.md"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def node_memory_dir(memory_path: str, messages_path: str) -> str:
    for path in (messages_path, memory_path):
        text = str(path or "").strip()
        if text:
            return os.path.dirname(text)
    return ""


def archive_paths_for_date(node_dir: str, date_text: str) -> dict[str, str]:
    if not node_dir:
        return {"dir": "", "memory_path": "", "messages_path": ""}
    safe_date = date_text if DATE_RE.match(date_text) else today_text()
    archive_dir = os.path.join(node_dir, ARCHIVE_DIRNAME, safe_date)
    return {
        "dir": archive_dir,
        "memory_path": os.path.join(archive_dir, MEMORY_FILENAME),
        "messages_path": os.path.join(archive_dir, MESSAGES_FILENAME),
    }


def active_paths(node_dir: str) -> dict[str, str]:
    if not node_dir:
        return {"dir": "", "memory_path": "", "messages_path": ""}
    return {
        "dir": node_dir,
        "memory_path": os.path.join(node_dir, MEMORY_FILENAME),
        "messages_path": os.path.join(node_dir, MESSAGES_FILENAME),
    }


def iter_archive_date_dirs(node_dir: str, *, reverse: bool) -> list[str]:
    archive_dir = os.path.join(node_dir, ARCHIVE_DIRNAME) if node_dir else ""
    if not archive_dir or not os.path.isdir(archive_dir):
        return []
    dates = [
        entry
        for entry in os.listdir(archive_dir)
        if DATE_RE.match(entry) and os.path.isdir(os.path.join(archive_dir, entry))
    ]
    dates.sort(reverse=reverse)
    return [os.path.join(archive_dir, date_text) for date_text in dates]


def record_date(record: dict[str, Any]) -> str:
    created_at = str((record or {}).get("created_at") or "").strip()
    if len(created_at) >= 10 and DATE_RE.match(created_at[:10]):
        return created_at[:10]
    return today_text()


def today_text() -> str:
    return datetime.now().strftime("%Y-%m-%d")
