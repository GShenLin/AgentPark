from __future__ import annotations

import os
from typing import Any


def validate_context_file_path(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("context.append_file paths cannot contain empty values")
    normalized = os.path.normpath(os.path.expanduser(text))
    if normalized in {"", "."}:
        raise ValueError("each context.append_file path must identify a file")
    if os.path.isabs(normalized):
        return normalized
    return normalized.replace("\\", "/")


def resolve_context_file_path(core: Any, graph_id: str, node_id: str, configured_path: str) -> str:
    node_dir = os.path.abspath(core.graph_runtime._node_dir(graph_id, node_id))
    normalized = validate_context_file_path(configured_path)
    if os.path.isabs(normalized):
        return os.path.abspath(normalized)
    return os.path.abspath(os.path.join(node_dir, normalized))


def read_node_context_file(core: Any, graph_id: str, node_id: str, configured_path: str, max_chars: int) -> str:
    file_path = resolve_context_file_path(core, graph_id, node_id, configured_path)
    if not os.path.exists(file_path):
        return ""
    if not os.path.isfile(file_path):
        raise ValueError(f"context path is not a file: {file_path}")
    with open(file_path, "r", encoding="utf-8") as handle:
        content = handle.read(max_chars + 1)
    if len(content) > max_chars:
        content = content[: max(0, max_chars - 3)].rstrip() + "..."
    return content.strip()
