from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime
from difflib import unified_diff
from typing import Any

from src.providers.agent_environment_context import resolve_agent_working_directory


FULL_MODEL_RETURN_CHAR_LIMIT = 32000


def summarize_file_changes(file_changes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    summaries: list[dict[str, Any]] = []
    total_additions = 0
    total_deletions = 0
    for change in file_changes:
        additions, deletions = _count_hunk_rows(change.get("hunks"))
        total_additions += additions
        total_deletions += deletions
        summary = {
            "operation": str(change.get("operation") or "update"),
            "path": str(change.get("path") or ""),
            "before_exists": bool(change.get("before_exists")),
            "after_exists": bool(change.get("after_exists")),
            "additions": additions,
            "deletions": deletions,
            "hunk_count": len(change.get("hunks") or []),
        }
        if change.get("move_to"):
            summary["move_to"] = str(change.get("move_to") or "")
        summaries.append(summary)
    return summaries, {"files": len(file_changes), "additions": total_additions, "deletions": total_deletions}


def full_file_changes_for_artifact(file_changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for change in file_changes:
        output.append({key: value for key, value in change.items() if not str(key).startswith("_")})
    return output


def write_patch_diff_artifact(
    *,
    operations: list[dict[str, Any]],
    changed_paths: set[str],
    file_changes: list[dict[str, Any]],
    stats: dict[str, int],
    agent: object = None,
) -> dict[str, Any]:
    artifact_id = f"apply_patch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    artifact_dir = _resolve_artifact_dir(agent)
    os.makedirs(artifact_dir, exist_ok=True)

    structured_path = os.path.join(artifact_dir, f"{artifact_id}.json")
    unified_diff_path = os.path.join(artifact_dir, f"{artifact_id}.diff")
    unified_text = build_unified_diff(file_changes)
    structured_payload = {
        "schema": "agentpark.apply_patch.diff.v1",
        "artifact_id": artifact_id,
        "operations": operations,
        "files_changed": sorted(changed_paths),
        "file_changes": full_file_changes_for_artifact(file_changes),
        "stats": stats,
        "unified_diff_path": unified_diff_path,
    }

    _atomic_write_text(unified_diff_path, unified_text, "utf-8")
    _atomic_write_text(structured_path, json.dumps(structured_payload, ensure_ascii=False, indent=2) + "\n", "utf-8")

    return {
        "available": True,
        "artifact_id": artifact_id,
        "artifact_path": structured_path,
        "structured_diff_path": structured_path,
        "unified_diff_path": unified_diff_path,
        "formats": ["structured", "unified"],
        "omitted_from_model": True,
        "reason": "summary_return_mode",
    }


def build_unified_diff(file_changes: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for change in file_changes:
        before_text = str(change.get("_before_text") or "")
        after_text = str(change.get("_after_text") or "")
        before_path = str(change.get("path") or "") if change.get("before_exists") else "/dev/null"
        after_target = str(change.get("move_to") or change.get("path") or "")
        after_path = after_target if change.get("after_exists") else "/dev/null"
        lines = list(
            unified_diff(
                before_text.splitlines(),
                after_text.splitlines(),
                fromfile=before_path,
                tofile=after_path,
                lineterm="",
            )
        )
        if lines:
            blocks.append("\n".join(lines))
    return "\n".join(blocks) + ("\n" if blocks else "")


def maybe_use_full_model_file_changes(
    *,
    payload: dict[str, Any],
    full_file_changes: list[dict[str, Any]],
    return_mode: str,
) -> dict[str, Any]:
    if return_mode != "full":
        return payload
    candidate = dict(payload)
    candidate["file_changes"] = full_file_changes_for_artifact(full_file_changes)
    candidate["diff"] = dict(candidate.get("diff") or {})
    candidate["diff"]["omitted_from_model"] = False
    candidate["diff"]["reason"] = "full_return_mode"
    text = json.dumps(candidate, ensure_ascii=False)
    if len(text) <= FULL_MODEL_RETURN_CHAR_LIMIT:
        return candidate
    payload["diff"] = dict(payload.get("diff") or {})
    payload["diff"]["reason"] = "full_return_mode_exceeded_model_return_limit"
    payload["diff"]["model_return_char_limit"] = FULL_MODEL_RETURN_CHAR_LIMIT
    return payload


def _count_hunk_rows(hunks: object) -> tuple[int, int]:
    additions = 0
    deletions = 0
    if not isinstance(hunks, list):
        return additions, deletions
    for hunk in hunks:
        if not isinstance(hunk, dict):
            continue
        rows = hunk.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or row.get("kind") == "context":
                continue
            if "before_text" in row:
                deletions += 1
            if "after_text" in row:
                additions += 1
    return additions, deletions


def _resolve_artifact_dir(agent: object = None) -> str:
    memory_path = _resolve_memory_path(agent)
    if memory_path:
        return os.path.join(os.path.dirname(os.path.abspath(memory_path)), "tool_artifacts", "patches")
    if agent is not None:
        return os.path.join(resolve_agent_working_directory(agent), ".agentpark", "patch_artifacts")
    return os.path.join(tempfile.gettempdir(), "agentpark_patch_artifacts")


def _resolve_memory_path(agent: object = None) -> str:
    for owner in (agent, getattr(agent, "memory", None)):
        value = str(getattr(owner, "current_memory_path", "") or "").strip()
        if value:
            return value
    return ""


def _atomic_write_text(file_path: str, content: str, encoding: str) -> None:
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temp_path = ""
    try:
        fd, temp_path = tempfile.mkstemp(prefix=".agentpark_patch_artifact_", dir=parent or ".")
        with os.fdopen(fd, "w", encoding=encoding, errors="replace") as handle:
            handle.write(content)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except Exception:
                pass
        os.replace(temp_path, file_path)
        temp_path = ""
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except Exception:
                pass


__all__ = [
    "FULL_MODEL_RETURN_CHAR_LIMIT",
    "build_unified_diff",
    "full_file_changes_for_artifact",
    "maybe_use_full_model_file_changes",
    "summarize_file_changes",
    "write_patch_diff_artifact",
]
