from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.task_direction_models import TaskDirectionContractError
from src.task_direction_models import TaskDirectionState


@dataclass(frozen=True)
class TaskDirectionCompletion:
    expected_revision: int
    state: TaskDirectionState

    @classmethod
    def from_payload(
        cls,
        payload: object,
        *,
        current_state: TaskDirectionState,
    ) -> "TaskDirectionCompletion":
        if not isinstance(payload, dict):
            raise TaskDirectionContractError("direction_completion must be an object")
        allowed = {"expected_revision", "evidence", "hypotheses", "risks", "criteria"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise TaskDirectionContractError(
                f"direction_completion has unknown fields: {', '.join(unknown)}"
            )
        expected_revision = payload.get("expected_revision")
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision <= 0
        ):
            raise TaskDirectionContractError(
                "direction_completion.expected_revision must be a positive integer"
            )

        state_payload = current_state.to_payload()
        additions = _objects(payload.get("evidence"), "direction_completion.evidence")
        existing_evidence_ids = {item["id"] for item in state_payload["evidence"]}
        addition_ids = _unique_item_ids(additions, "direction_completion.evidence")
        collisions = sorted(existing_evidence_ids & addition_ids)
        if collisions:
            raise TaskDirectionContractError(
                "direction_completion.evidence reuses existing ids: " + ", ".join(collisions)
            )
        state_payload["evidence"].extend(additions)

        _apply_resolutions(
            state_payload["hypotheses"],
            _objects(payload.get("hypotheses"), "direction_completion.hypotheses"),
            label="direction_completion.hypotheses",
            allowed_statuses={"confirmed", "rejected"},
            required_ids=None,
        )
        _apply_resolutions(
            state_payload["unresolved_risks"],
            _objects(payload.get("risks"), "direction_completion.risks"),
            label="direction_completion.risks",
            allowed_statuses={"resolved"},
            required_ids=None,
        )
        pending_criteria = {
            item["id"] for item in state_payload["done_criteria"] if item["status"] == "pending"
        }
        _apply_resolutions(
            state_payload["done_criteria"],
            _objects(payload.get("criteria"), "direction_completion.criteria"),
            label="direction_completion.criteria",
            allowed_statuses={"met", "blocked"},
            required_ids=pending_criteria,
        )
        return cls(
            expected_revision=expected_revision,
            state=TaskDirectionState.from_payload(state_payload),
        )


def _objects(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TaskDirectionContractError(f"{label} must be an array")
    output = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise TaskDirectionContractError(f"{label}[{index}] must be an object")
        output.append(dict(item))
    return output


def _unique_item_ids(items: list[dict[str, Any]], label: str) -> set[str]:
    values = []
    for index, item in enumerate(items):
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            raise TaskDirectionContractError(f"{label}[{index}].id is required")
        values.append(item_id)
    if len(set(values)) != len(values):
        raise TaskDirectionContractError(f"{label} contains duplicate ids")
    return set(values)


def _apply_resolutions(
    current_items: list[dict[str, Any]],
    resolutions: list[dict[str, Any]],
    *,
    label: str,
    allowed_statuses: set[str],
    required_ids: set[str] | None,
) -> None:
    resolution_ids = _unique_item_ids(resolutions, label)
    current_by_id = {item["id"]: item for item in current_items}
    unknown = sorted(resolution_ids - set(current_by_id))
    if unknown:
        valid_ids = sorted(current_by_id)
        valid_detail = ", ".join(valid_ids) if valid_ids else "(none)"
        raise TaskDirectionContractError(
            f"{label} references unknown ids: {', '.join(unknown)}; "
            f"valid ids: {valid_detail}"
        )
    if required_ids is not None and resolution_ids != required_ids:
        missing = sorted(required_ids - resolution_ids)
        unexpected = sorted(resolution_ids - required_ids)
        details = []
        if missing:
            details.append("missing pending ids: " + ", ".join(missing))
        if unexpected:
            details.append("already resolved ids: " + ", ".join(unexpected))
        details.append("required pending ids: " + ", ".join(sorted(required_ids)))
        raise TaskDirectionContractError(
            f"{label} must resolve every pending criterion; " + "; ".join(details)
        )

    for index, resolution in enumerate(resolutions):
        allowed = {"id", "status", "evidence_ids"}
        extra = sorted(set(resolution) - allowed)
        if extra:
            raise TaskDirectionContractError(
                f"{label}[{index}] has unknown fields: {', '.join(extra)}"
            )
        status = str(resolution.get("status") or "").strip()
        if status not in allowed_statuses:
            raise TaskDirectionContractError(
                f"{label}[{index}].status must be one of: {', '.join(sorted(allowed_statuses))}"
            )
        evidence_ids = resolution.get("evidence_ids")
        if not isinstance(evidence_ids, list):
            raise TaskDirectionContractError(f"{label}[{index}].evidence_ids must be an array")
        current_by_id[str(resolution["id"])].update(
            {"status": status, "evidence_ids": list(evidence_ids)}
        )
