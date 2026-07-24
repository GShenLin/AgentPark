from __future__ import annotations

import pytest

from src.workspace_checkpoint_policy import CHECKPOINT_NONE
from src.workspace_checkpoint_policy import CHECKPOINT_RETAIN
from src.workspace_checkpoint_policy import CHECKPOINT_RETIRE_VERIFIED
from src.workspace_checkpoint_policy import WorkspaceCheckpointPolicyError
from src.workspace_checkpoint_policy import checkpoint_policy_from_tool_arguments
from src.workspace_checkpoint_policy import has_ordered_direction_patch
from src.workspace_checkpoint_policy import normalize_workspace_checkpoint_policy
from src.workspace_checkpoint_policy import validate_workspace_checkpoint_policy


def _handoff_stages() -> list[dict]:
    return [
        {
            "id": "direction",
            "operations": [{"id": "update", "kind": "update_task_direction"}],
        },
        {
            "id": "patch",
            "operations": [{"id": "apply", "kind": "apply_patch"}],
        },
    ]


def _read_stages() -> list[dict]:
    return [
        {
            "id": "read",
            "operations": [{"id": "source", "kind": "read_file"}],
        }
    ]


@pytest.mark.parametrize(
    "policy",
    [CHECKPOINT_NONE, CHECKPOINT_RETAIN, CHECKPOINT_RETIRE_VERIFIED],
)
def test_normalize_workspace_checkpoint_policy_accepts_exact_values(policy):
    assert normalize_workspace_checkpoint_policy(policy) == policy


@pytest.mark.parametrize("value", [True, 1, [], {}, "later", " retain_until_next_handoff "])
def test_normalize_workspace_checkpoint_policy_rejects_non_contract_values(value):
    with pytest.raises(WorkspaceCheckpointPolicyError):
        normalize_workspace_checkpoint_policy(value)


def test_ordered_handoff_requires_explicit_lifecycle_policy():
    with pytest.raises(WorkspaceCheckpointPolicyError, match="requires an explicit"):
        validate_workspace_checkpoint_policy(_handoff_stages(), CHECKPOINT_NONE)


@pytest.mark.parametrize("policy", [CHECKPOINT_RETAIN, CHECKPOINT_RETIRE_VERIFIED])
def test_ordered_handoff_accepts_explicit_lifecycle_policy(policy):
    assert validate_workspace_checkpoint_policy(_handoff_stages(), policy) == policy


@pytest.mark.parametrize("policy", [CHECKPOINT_RETAIN, CHECKPOINT_RETIRE_VERIFIED])
def test_non_handoff_rejects_retirement_policy(policy):
    with pytest.raises(WorkspaceCheckpointPolicyError, match="only for an ordered"):
        validate_workspace_checkpoint_policy(_read_stages(), policy)


def test_non_handoff_accepts_none_and_order_detection_is_strict():
    assert validate_workspace_checkpoint_policy(_read_stages(), CHECKPOINT_NONE) == CHECKPOINT_NONE
    assert has_ordered_direction_patch(_handoff_stages()) is True
    assert has_ordered_direction_patch(list(reversed(_handoff_stages()))) is False


def test_tool_argument_policy_returns_only_valid_handoff_policy():
    assert checkpoint_policy_from_tool_arguments(
        {
            "stages": _handoff_stages(),
            "context_checkpoint": CHECKPOINT_RETIRE_VERIFIED,
        }
    ) == CHECKPOINT_RETIRE_VERIFIED
    assert checkpoint_policy_from_tool_arguments({"stages": _handoff_stages()}) is None
    assert checkpoint_policy_from_tool_arguments(
        {
            "stages": _read_stages(),
            "context_checkpoint": CHECKPOINT_RETIRE_VERIFIED,
        }
    ) is None
