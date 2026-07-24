from __future__ import annotations

from datetime import datetime
import json
import os
import uuid

from src.file_transaction import atomic_write_text


class ToolResultArtifactStoreError(RuntimeError):
    """Raised when a required full tool-result artifact cannot be persisted."""


def store_tool_result_artifact(
    owner: object,
    *,
    tool_name: object,
    call_id: object,
    content: object,
    reason: object = "",
) -> str:
    memory_path = _memory_path(owner)
    base_dir = os.path.dirname(os.path.abspath(memory_path))
    artifact_dir = os.path.join(base_dir, "tool_artifacts")
    os.makedirs(artifact_dir, exist_ok=True)

    resolved_tool = str(tool_name or "").strip() or "tool"
    resolved_call = str(call_id or "").strip()
    safe_tool = _safe_component(resolved_tool, fallback="tool")
    safe_call = _safe_component(resolved_call, fallback="call")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{stamp}_{safe_tool}_{safe_call}_{uuid.uuid4().hex[:8]}.json"
    path = os.path.join(artifact_dir, filename)
    text = str(content or "")
    payload = {
        "tool": resolved_tool,
        "call_id": resolved_call,
        "reason": str(reason or "").strip(),
        "content_chars": len(text),
        "content": text,
    }
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _memory_path(owner: object) -> str:
    memory_path = str(getattr(owner, "current_memory_path", "") or "").strip()
    if not memory_path:
        memory = getattr(owner, "memory", None)
        memory_path = str(getattr(memory, "current_memory_path", "") or "").strip()
    if not memory_path:
        raise ToolResultArtifactStoreError(
            "tool result artifact storage requires a configured memory path"
        )
    return memory_path


def _safe_component(value: str, *, fallback: str) -> str:
    safe = "".join(
        character
        if character.isalnum() or character in {"-", "_"}
        else "_"
        for character in value
    )
    return safe or fallback
