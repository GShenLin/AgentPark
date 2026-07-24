import pytest

from src.workspace_patch_requirements import WorkspacePatchRequirementError
from src.workspace_patch_requirements import validate_workspace_patch_requirements


PATCH = """*** Begin Patch
*** Update File: example.py
@@
-legacy task.arguments
+canonical RemoteTaskEnvelope.arguments
+new boundary assertion
*** End Patch
"""


def test_patch_requirements_accept_declared_replacement_and_addition():
    parsed = validate_workspace_patch_requirements(
        PATCH,
        [
            {
                "id": "owner_label",
                "kind": "replacement",
                "old_text": "legacy task.arguments",
                "new_text": "canonical RemoteTaskEnvelope.arguments",
            },
            {
                "id": "boundary_assertion",
                "kind": "addition",
                "text": "new boundary assertion",
            },
        ],
    )

    assert [item["id"] for item in parsed] == ["owner_label", "boundary_assertion"]


@pytest.mark.parametrize(
    ("requirements", "message"),
    [
        ([], "non-empty array"),
        (
            [
                {
                    "id": "owner_label",
                    "kind": "replacement",
                    "old_text": "not removed",
                    "new_text": "canonical RemoteTaskEnvelope.arguments",
                }
            ],
            "old_text removal",
        ),
        (
            [
                {
                    "id": "owner_label",
                    "kind": "replacement",
                    "old_text": "legacy task.arguments",
                    "new_text": "not added",
                }
            ],
            "new_text addition",
        ),
        (
            [
                {
                    "id": "missing_addition",
                    "kind": "addition",
                    "text": "not added",
                }
            ],
            "declared addition",
        ),
    ],
)
def test_patch_requirements_reject_missing_declared_changes(requirements, message):
    with pytest.raises(WorkspacePatchRequirementError, match=message):
        validate_workspace_patch_requirements(PATCH, requirements)


def test_patch_requirements_reject_duplicate_ids_and_unknown_fields():
    with pytest.raises(WorkspacePatchRequirementError, match="duplicate id"):
        validate_workspace_patch_requirements(
            PATCH,
            [
                {"id": "same", "kind": "addition", "text": "new boundary assertion"},
                {"id": "same", "kind": "addition", "text": "new boundary assertion"},
            ],
        )

    with pytest.raises(WorkspacePatchRequirementError, match="unknown fields"):
        validate_workspace_patch_requirements(
            PATCH,
            [
                {
                    "id": "addition",
                    "kind": "addition",
                    "text": "new boundary assertion",
                    "unexpected": True,
                }
            ],
        )
