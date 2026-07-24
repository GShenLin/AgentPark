from __future__ import annotations

from typing import Any


CHECKPOINT_NONE = "none"
CHECKPOINT_RETAIN = "retain_until_next_handoff"
CHECKPOINT_RETIRE_VERIFIED = "retire_after_verified"
CHECKPOINT_POLICIES = frozenset(
    {
        CHECKPOINT_NONE,
        CHECKPOINT_RETAIN,
        CHECKPOINT_RETIRE_VERIFIED,
    }
)


class WorkspaceCheckpointPolicyError(ValueError):
    """Raised when workspace checkpoint lifecycle metadata is inconsistent."""


def normalize_workspace_checkpoint_policy(value: object) -> str:
    if value is None:
        return CHECKPOINT_NONE
    if not isinstance(value, str):
        raise WorkspaceCheckpointPolicyError(
            "context_checkpoint must be a string policy"
        )
    policy = value.strip()
    if policy != value:
        raise WorkspaceCheckpointPolicyError(
            "context_checkpoint must not contain surrounding whitespace"
        )
    if policy not in CHECKPOINT_POLICIES:
        raise WorkspaceCheckpointPolicyError(
            "context_checkpoint must be one of: "
            + ", ".join(sorted(CHECKPOINT_POLICIES))
        )
    return policy


def validate_workspace_checkpoint_policy(
    stages: object,
    context_checkpoint: object,
) -> str:
    policy = normalize_workspace_checkpoint_policy(context_checkpoint)
    ordered_handoff = has_ordered_direction_patch(stages)
    if ordered_handoff and policy == CHECKPOINT_NONE:
        raise WorkspaceCheckpointPolicyError(
            "ordered update_task_direction -> apply_patch handoff requires an "
            "explicit context_checkpoint lifecycle policy"
        )
    if not ordered_handoff and policy != CHECKPOINT_NONE:
        raise WorkspaceCheckpointPolicyError(
            "context_checkpoint lifecycle policy is valid only for an ordered "
            "update_task_direction -> apply_patch handoff"
        )
    return policy


def checkpoint_policy_from_tool_arguments(arguments: object) -> str | None:
    if not isinstance(arguments, dict):
        return None
    try:
        policy = validate_workspace_checkpoint_policy(
            arguments.get("stages"),
            arguments.get("context_checkpoint"),
        )
    except WorkspaceCheckpointPolicyError:
        return None
    return policy if policy != CHECKPOINT_NONE else None


def has_ordered_direction_patch(stages: object) -> bool:
    if not isinstance(stages, list):
        return False
    direction_stage: int | None = None
    patch_stage: int | None = None
    for stage_index, stage in enumerate(stages):
        operations = stage.get("operations") if isinstance(stage, dict) else None
        for operation in operations if isinstance(operations, list) else []:
            kind = (
                str(operation.get("kind") or "").strip()
                if isinstance(operation, dict)
                else ""
            )
            if kind == "update_task_direction" and direction_stage is None:
                direction_stage = stage_index
            if kind == "apply_patch" and patch_stage is None:
                patch_stage = stage_index
    return (
        direction_stage is not None
        and patch_stage is not None
        and direction_stage < patch_stage
    )


__all__ = [
    "CHECKPOINT_NONE",
    "CHECKPOINT_POLICIES",
    "CHECKPOINT_RETAIN",
    "CHECKPOINT_RETIRE_VERIFIED",
    "WorkspaceCheckpointPolicyError",
    "checkpoint_policy_from_tool_arguments",
    "has_ordered_direction_patch",
    "normalize_workspace_checkpoint_policy",
    "validate_workspace_checkpoint_policy",
]
