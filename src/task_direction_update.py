from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.task_direction_models import TaskDirectionContractError
from src.task_direction_models import TaskDirectionState


_TERMINAL_HYPOTHESIS_STATUSES = {"confirmed", "rejected"}
_TERMINAL_RISK_STATUSES = {"resolved"}
_TERMINAL_CRITERION_STATUSES = {"met", "blocked"}


@dataclass(frozen=True)
class TaskDirectionUpdate:
    state: TaskDirectionState
    added_evidence_ids: tuple[str, ...]
    changed_hypothesis_ids: tuple[str, ...]
    changed_risk_ids: tuple[str, ...]
    changed_criterion_ids: tuple[str, ...]

    @classmethod
    def from_payload(
        cls,
        payload: object,
        *,
        current_state: TaskDirectionState,
    ) -> "TaskDirectionUpdate":
        if not isinstance(payload, dict):
            raise TaskDirectionContractError("task direction update must be an object")
        allowed = {"evidence", "hypotheses", "risks", "criteria"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise TaskDirectionContractError(
                "task direction update has unknown fields: " + ", ".join(unknown)
            )

        evidence = _objects(payload.get("evidence"), "task direction update.evidence")
        hypotheses = _objects(payload.get("hypotheses"), "task direction update.hypotheses")
        risks = _objects(payload.get("risks"), "task direction update.risks")
        criteria = _objects(payload.get("criteria"), "task direction update.criteria")
        if not any((evidence, hypotheses, risks, criteria)):
            raise TaskDirectionContractError("task direction update must contain at least one change")

        state_payload = current_state.to_payload()
        added_evidence_ids = _append_new_evidence(state_payload["evidence"], evidence)
        changed_hypothesis_ids = _upsert_items(
            state_payload["hypotheses"],
            hypotheses,
            label="task direction update.hypotheses",
            immutable_fields=("statement",),
            terminal_statuses=_TERMINAL_HYPOTHESIS_STATUSES,
        )
        changed_risk_ids = _upsert_items(
            state_payload["unresolved_risks"],
            risks,
            label="task direction update.risks",
            immutable_fields=("severity", "statement"),
            terminal_statuses=_TERMINAL_RISK_STATUSES,
        )
        changed_criterion_ids = _upsert_items(
            state_payload["done_criteria"],
            criteria,
            label="task direction update.criteria",
            immutable_fields=("statement",),
            terminal_statuses=_TERMINAL_CRITERION_STATUSES,
        )
        next_state = TaskDirectionState.from_payload(state_payload)
        return cls(
            state=next_state,
            added_evidence_ids=tuple(added_evidence_ids),
            changed_hypothesis_ids=tuple(changed_hypothesis_ids),
            changed_risk_ids=tuple(changed_risk_ids),
            changed_criterion_ids=tuple(changed_criterion_ids),
        )

    def receipt(self) -> dict[str, Any]:
        return {
            "added_evidence_ids": list(self.added_evidence_ids),
            "changed_ids": {
                "hypotheses": list(self.changed_hypothesis_ids),
                "risks": list(self.changed_risk_ids),
                "criteria": list(self.changed_criterion_ids),
            },
            "state_counts": {
                "hypotheses": len(self.state.hypotheses),
                "evidence": len(self.state.evidence),
                "risks": len(self.state.unresolved_risks),
                "criteria": len(self.state.done_criteria),
            },
        }


def _objects(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise TaskDirectionContractError(f"{label} must be an array")
    output = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise TaskDirectionContractError(f"{label}[{index}] must be an object")
        output.append(dict(item))
    return output


def _append_new_evidence(
    current_items: list[dict[str, Any]],
    additions: list[dict[str, Any]],
) -> list[str]:
    existing_ids = {str(item["id"]) for item in current_items}
    addition_ids = _unique_ids(additions, "task direction update.evidence")
    collisions = sorted(existing_ids & set(addition_ids))
    if collisions:
        raise TaskDirectionContractError(
            "task direction update.evidence reuses existing ids: " + ", ".join(collisions)
        )
    current_items.extend(additions)
    return addition_ids


def _upsert_items(
    current_items: list[dict[str, Any]],
    updates: list[dict[str, Any]],
    *,
    label: str,
    immutable_fields: tuple[str, ...],
    terminal_statuses: set[str],
) -> list[str]:
    update_ids = _unique_ids(updates, label)
    current_by_id = {str(item["id"]): item for item in current_items}
    for index, update in enumerate(updates):
        item_id = update_ids[index]
        current = current_by_id.get(item_id)
        if current is None:
            current_items.append(update)
            current_by_id[item_id] = update
            continue
        if current == update:
            raise TaskDirectionContractError(
                f"{label}[{index}] does not change existing id {item_id}"
            )
        for field in immutable_fields:
            if update.get(field) != current.get(field):
                raise TaskDirectionContractError(
                    f"{label}[{index}].{field} cannot change for existing id {item_id}"
                )
        current_status = str(current.get("status") or "")
        next_status = str(update.get("status") or "")
        if current_status in terminal_statuses and next_status != current_status:
            raise TaskDirectionContractError(
                f"{label}[{index}].status cannot change terminal status "
                f"{current_status} for existing id {item_id}"
            )
        current.clear()
        current.update(update)
    return update_ids


def _unique_ids(items: list[dict[str, Any]], label: str) -> list[str]:
    values = []
    for index, item in enumerate(items):
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            raise TaskDirectionContractError(f"{label}[{index}].id is required")
        values.append(item_id)
    if len(set(values)) != len(values):
        raise TaskDirectionContractError(f"{label} contains duplicate ids")
    return values
