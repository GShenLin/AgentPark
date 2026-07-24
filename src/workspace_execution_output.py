from __future__ import annotations

import json
from typing import Any

from src.tool_result_artifact_store import store_tool_result_artifact
from src.workspace_execution import WorkspaceExecutionContractError


def serialize_workspace_result(result: dict[str, Any], *, agent: object) -> str:
    serialized = json.dumps(result, ensure_ascii=False)
    submission_limit = _submission_limit(agent)
    if submission_limit is None or len(serialized) <= submission_limit:
        return serialized

    artifact_path = store_tool_result_artifact(
        agent,
        tool_name="workspace_exec",
        call_id="",
        content=serialized,
        reason=(
            "workspace_exec result exceeded "
            f"agent.config.toolResultSubmissionMaxChars={submission_limit}"
        ),
    )
    maximum_result_chars = max(
        (
            len(json.dumps(operation.get("result"), ensure_ascii=False))
            for stage in result.get("stages", [])
            for operation in stage.get("operations", [])
        ),
        default=0,
    )
    low, high = 0, min(maximum_result_chars, submission_limit)
    best_serialized = None
    while low <= high:
        preview_limit = (low + high) // 2
        candidate = _compacted_payload(
            result,
            artifact_path=artifact_path,
            original_result_chars=len(serialized),
            submission_limit=submission_limit,
            preview_limit=preview_limit,
        )
        candidate_serialized = json.dumps(candidate, ensure_ascii=False)
        if len(candidate_serialized) <= submission_limit:
            best_serialized = candidate_serialized
            low = preview_limit + 1
        else:
            high = preview_limit - 1
    if best_serialized is None:
        raise WorkspaceExecutionContractError(
            "workspace_exec compact metadata exceeds "
            "agent.config.toolResultSubmissionMaxChars"
        )
    return best_serialized


def _submission_limit(agent: object) -> int | None:
    config = getattr(agent, "config", None)
    if not isinstance(config, dict) or "toolResultSubmissionMaxChars" not in config:
        return None
    value = config.get("toolResultSubmissionMaxChars")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WorkspaceExecutionContractError(
            "agent.config.toolResultSubmissionMaxChars must be a positive integer"
        )
    return value


def _compacted_payload(
    result: dict[str, Any],
    *,
    artifact_path: str,
    original_result_chars: int,
    submission_limit: int,
    preview_limit: int,
) -> dict[str, Any]:
    stages = []
    for stage in result.get("stages", []):
        operations = []
        for operation in stage.get("operations", []):
            operation_result = operation.get("result")
            operation_text = json.dumps(operation_result, ensure_ascii=False)
            operations.append(
                {
                    "id": operation.get("id"),
                    "kind": operation.get("kind"),
                    "status": operation.get("status"),
                    "result": {
                        "compacted": True,
                        "original_chars": len(operation_text),
                        "preview": _head_tail(operation_text, preview_limit),
                    },
                }
            )
        stages.append(
            {
                "stage_id": stage.get("stage_id"),
                "status": stage.get("status"),
                "operations": operations,
            }
        )
    return {
        "status": result.get("status"),
        "stage_count": result.get("stage_count"),
        "operation_count": result.get("operation_count"),
        "result_compacted": True,
        "original_result_chars": original_result_chars,
        "artifact_path": artifact_path,
        "compaction": {
            "strategy": "per_operation_head_tail",
            "configured_submission_max_chars": submission_limit,
            "preview_chars_per_operation": preview_limit,
        },
        "stages": stages,
    }


def _head_tail(value: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    omitted = len(value) - limit
    marker = f"... <{omitted} chars omitted> ..."
    if len(marker) >= limit:
        return value[:limit]
    available = limit - len(marker)
    head_chars = max(1, available // 3)
    tail_chars = available - head_chars
    return value[:head_chars] + marker + value[-tail_chars:]
