from __future__ import annotations

import os
from typing import Any

from src.operational_memory import MEMORY_FILENAME
from src.operational_memory import build_operational_memory_summary
from src.operational_memory import operational_memory_snapshot


OPERATIONAL_MEMORY_SUMMARY_MAX_ITEMS = 5
OPERATIONAL_MEMORY_SUMMARY_MAX_CHARS = 2000


def build_operational_memory_notice_context(
    *,
    node_dir: str = "",
    memory_path: str = "",
) -> dict[str, Any]:
    directory = str(node_dir or "").strip()
    if not directory:
        memory_file = str(memory_path or "").strip()
        directory = os.path.dirname(os.path.abspath(memory_file)) if memory_file else ""
    operational_memory_path = os.path.join(directory, MEMORY_FILENAME) if directory else ""
    summary = ""
    summary_error = ""
    if operational_memory_path:
        try:
            summary = build_operational_memory_summary(
                operational_memory_path,
                max_items=OPERATIONAL_MEMORY_SUMMARY_MAX_ITEMS,
                max_chars=OPERATIONAL_MEMORY_SUMMARY_MAX_CHARS,
            )
        except Exception as exc:
            summary_error = f"{type(exc).__name__}: {exc}"
    snapshot = operational_memory_snapshot(operational_memory_path) if operational_memory_path else ""
    payload = {
        "operational_memory_path": operational_memory_path,
        "summary": summary,
        "summary_chars": len(summary),
        "summary_max_chars": OPERATIONAL_MEMORY_SUMMARY_MAX_CHARS,
        "summary_max_items": OPERATIONAL_MEMORY_SUMMARY_MAX_ITEMS,
        "snapshot_chars": len(snapshot),
    }
    if summary_error:
        payload["summary_error"] = summary_error
    return payload


__all__ = [
    "OPERATIONAL_MEMORY_SUMMARY_MAX_CHARS",
    "OPERATIONAL_MEMORY_SUMMARY_MAX_ITEMS",
    "build_operational_memory_notice_context",
]
