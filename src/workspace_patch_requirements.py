from __future__ import annotations

import re
from typing import Any


MAX_PATCH_REQUIREMENTS = 20
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")


class WorkspacePatchRequirementError(ValueError):
    """Raised before mutation when a patch omits a declared critical change."""


def validate_workspace_patch_requirements(
    patch: object,
    requirements: object,
) -> tuple[dict[str, str], ...]:
    if not isinstance(patch, str) or not patch.strip():
        raise WorkspacePatchRequirementError("patch must be a non-empty string")
    parsed = _parse_requirements(requirements)
    added_text, removed_text = _changed_text(patch)
    for item in parsed:
        requirement_id = item["id"]
        if item["kind"] == "addition":
            if item["text"] not in added_text:
                raise WorkspacePatchRequirementError(
                    f"patch requirement {requirement_id!r} is missing declared addition"
                )
            continue
        if item["old_text"] not in removed_text:
            raise WorkspacePatchRequirementError(
                f"patch requirement {requirement_id!r} is missing declared old_text removal"
            )
        if item["new_text"] not in added_text:
            raise WorkspacePatchRequirementError(
                f"patch requirement {requirement_id!r} is missing declared new_text addition"
            )
    return tuple(parsed)


def _parse_requirements(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise WorkspacePatchRequirementError(
            "required_changes must be a non-empty array"
        )
    if len(value) > MAX_PATCH_REQUIREMENTS:
        raise WorkspacePatchRequirementError(
            f"required_changes cannot contain more than {MAX_PATCH_REQUIREMENTS} items"
        )
    output: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(value):
        label = f"required_changes[{index}]"
        if not isinstance(raw_item, dict):
            raise WorkspacePatchRequirementError(f"{label} must be an object")
        kind = raw_item.get("kind")
        allowed = (
            {"id", "kind", "text"}
            if kind == "addition"
            else {"id", "kind", "old_text", "new_text"}
        )
        unknown = sorted(set(raw_item) - allowed)
        if unknown:
            raise WorkspacePatchRequirementError(
                f"{label} has unknown fields: {', '.join(unknown)}"
            )
        requirement_id = _identifier(raw_item.get("id"), f"{label}.id")
        if requirement_id in seen_ids:
            raise WorkspacePatchRequirementError(
                f"required_changes contains duplicate id: {requirement_id}"
            )
        seen_ids.add(requirement_id)
        if kind == "addition":
            output.append(
                {
                    "id": requirement_id,
                    "kind": kind,
                    "text": _text(raw_item.get("text"), f"{label}.text"),
                }
            )
            continue
        if kind != "replacement":
            raise WorkspacePatchRequirementError(
                f"{label}.kind must be one of: addition, replacement"
            )
        old_text = _text(raw_item.get("old_text"), f"{label}.old_text")
        new_text = _text(raw_item.get("new_text"), f"{label}.new_text")
        if old_text == new_text:
            raise WorkspacePatchRequirementError(
                f"{label} old_text and new_text must differ"
            )
        output.append(
            {
                "id": requirement_id,
                "kind": kind,
                "old_text": old_text,
                "new_text": new_text,
            }
        )
    return output


def _changed_text(patch: str) -> tuple[str, str]:
    added_lines: list[str] = []
    removed_lines: list[str] = []
    for line in patch.splitlines():
        if line.startswith("***"):
            continue
        if line.startswith("+"):
            added_lines.append(line[1:])
        elif line.startswith("-"):
            removed_lines.append(line[1:])
    return "\n".join(added_lines), "\n".join(removed_lines)


def _identifier(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise WorkspacePatchRequirementError(f"{label} must match {_ID_RE.pattern}")
    return text


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise WorkspacePatchRequirementError(f"{label} must be a non-empty string")
    return value
