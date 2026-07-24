from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable


TASK_DIRECTION_SCHEMA_VERSION = 2
MAX_OBJECTIVE_CHARS = 8_000
MAX_ITEM_STATEMENT_CHARS = 4_000
MAX_SOURCE_CHARS = 2_000
MAX_HYPOTHESES = 50
MAX_EVIDENCE = 100
MAX_RISKS = 50
MAX_DONE_CRITERIA = 50
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")


class TaskDirectionContractError(ValueError):
    """Raised when a task direction snapshot violates its schema or invariants."""


@dataclass(frozen=True)
class DirectionHypothesis:
    id: str
    statement: str
    status: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DirectionEvidence:
    id: str
    kind: str
    summary: str
    source: str


@dataclass(frozen=True)
class DirectionRisk:
    id: str
    severity: str
    statement: str
    status: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class DirectionCriterion:
    id: str
    statement: str
    status: str
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True)
class TaskDirectionState:
    objective: str
    hypotheses: tuple[DirectionHypothesis, ...]
    evidence: tuple[DirectionEvidence, ...]
    unresolved_risks: tuple[DirectionRisk, ...]
    done_criteria: tuple[DirectionCriterion, ...]

    @classmethod
    def from_payload(cls, payload: object) -> "TaskDirectionState":
        if not isinstance(payload, dict):
            raise TaskDirectionContractError("state must be an object")
        _reject_unknown_keys(
            payload,
            {"objective", "hypotheses", "evidence", "unresolved_risks", "done_criteria"},
            "state",
        )
        objective = _required_text(payload.get("objective"), "state.objective", MAX_OBJECTIVE_CHARS)
        evidence = tuple(
            _parse_evidence(item, index)
            for index, item in enumerate(
                _required_list(payload.get("evidence"), "state.evidence", MAX_EVIDENCE)
            )
        )
        evidence_ids = _unique_ids(evidence, "state.evidence")
        hypotheses = tuple(
            _parse_hypothesis(item, index, evidence_ids)
            for index, item in enumerate(
                _required_list(payload.get("hypotheses"), "state.hypotheses", MAX_HYPOTHESES)
            )
        )
        risks = tuple(
            _parse_risk(item, index, evidence_ids)
            for index, item in enumerate(
                _required_list(payload.get("unresolved_risks"), "state.unresolved_risks", MAX_RISKS)
            )
        )
        criteria = tuple(
            _parse_criterion(item, index, evidence_ids)
            for index, item in enumerate(
                _required_list(payload.get("done_criteria"), "state.done_criteria", MAX_DONE_CRITERIA)
            )
        )
        _unique_ids(hypotheses, "state.hypotheses")
        _unique_ids(risks, "state.unresolved_risks")
        _unique_ids(criteria, "state.done_criteria")
        if not criteria:
            raise TaskDirectionContractError("state.done_criteria must contain at least one item")
        return cls(
            objective=objective,
            hypotheses=hypotheses,
            evidence=evidence,
            unresolved_risks=risks,
            done_criteria=criteria,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "hypotheses": [_item_payload(item) for item in self.hypotheses],
            "evidence": [_item_payload(item) for item in self.evidence],
            "unresolved_risks": [_item_payload(item) for item in self.unresolved_risks],
            "done_criteria": [_item_payload(item) for item in self.done_criteria],
        }


def _parse_hypothesis(
    payload: object,
    index: int,
    evidence_ids: set[str],
) -> DirectionHypothesis:
    label = f"state.hypotheses[{index}]"
    item = _item_object(payload, label, {"id", "statement", "status", "evidence_ids"})
    status = _enum(item.get("status"), f"{label}.status", {"open", "confirmed", "rejected"})
    references = _evidence_references(item.get("evidence_ids"), f"{label}.evidence_ids", evidence_ids)
    if status != "open" and not references:
        raise TaskDirectionContractError(f"{label}.evidence_ids is required when status={status}")
    return DirectionHypothesis(
        id=_identifier(item.get("id"), f"{label}.id"),
        statement=_required_text(item.get("statement"), f"{label}.statement", MAX_ITEM_STATEMENT_CHARS),
        status=status,
        evidence_ids=references,
    )


def _parse_evidence(payload: object, index: int) -> DirectionEvidence:
    label = f"state.evidence[{index}]"
    item = _item_object(payload, label, {"id", "kind", "summary", "source"})
    return DirectionEvidence(
        id=_identifier(item.get("id"), f"{label}.id"),
        kind=_enum(
            item.get("kind"),
            f"{label}.kind",
            {"source", "test", "build", "security", "config", "worktree", "runtime", "other"},
        ),
        summary=_required_text(item.get("summary"), f"{label}.summary", MAX_ITEM_STATEMENT_CHARS),
        source=_required_text(item.get("source"), f"{label}.source", MAX_SOURCE_CHARS),
    )


def _parse_risk(payload: object, index: int, evidence_ids: set[str]) -> DirectionRisk:
    label = f"state.unresolved_risks[{index}]"
    item = _item_object(payload, label, {"id", "severity", "statement", "status", "evidence_ids"})
    status = _enum(item.get("status"), f"{label}.status", {"open", "resolved"})
    references = _evidence_references(item.get("evidence_ids"), f"{label}.evidence_ids", evidence_ids)
    if status == "resolved" and not references:
        raise TaskDirectionContractError(f"{label}.evidence_ids is required when status=resolved")
    return DirectionRisk(
        id=_identifier(item.get("id"), f"{label}.id"),
        severity=_enum(item.get("severity"), f"{label}.severity", {"P0", "P1", "P2", "P3"}),
        statement=_required_text(item.get("statement"), f"{label}.statement", MAX_ITEM_STATEMENT_CHARS),
        status=status,
        evidence_ids=references,
    )


def _parse_criterion(payload: object, index: int, evidence_ids: set[str]) -> DirectionCriterion:
    label = f"state.done_criteria[{index}]"
    item = _item_object(payload, label, {"id", "statement", "status", "evidence_ids"})
    status = _enum(item.get("status"), f"{label}.status", {"pending", "met", "blocked"})
    references = _evidence_references(item.get("evidence_ids"), f"{label}.evidence_ids", evidence_ids)
    if status == "met" and not references:
        raise TaskDirectionContractError(f"{label}.evidence_ids is required when status=met")
    return DirectionCriterion(
        id=_identifier(item.get("id"), f"{label}.id"),
        statement=_required_text(item.get("statement"), f"{label}.statement", MAX_ITEM_STATEMENT_CHARS),
        status=status,
        evidence_ids=references,
    )


def _evidence_references(value: object, field_name: str, evidence_ids: set[str]) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TaskDirectionContractError(f"{field_name} must be an array")
    references = tuple(_identifier(item, field_name) for item in value)
    if len(set(references)) != len(references):
        raise TaskDirectionContractError(f"{field_name} contains duplicate ids")
    missing = sorted(set(references) - evidence_ids)
    if missing:
        raise TaskDirectionContractError(
            f"{field_name} references unknown evidence ids: {', '.join(missing)}"
        )
    return references


def _required_list(value: object, field_name: str, limit: int) -> list[Any]:
    if not isinstance(value, list):
        raise TaskDirectionContractError(f"{field_name} must be an array")
    if len(value) > limit:
        raise TaskDirectionContractError(f"{field_name} cannot contain more than {limit} items")
    return value


def _item_object(value: object, label: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TaskDirectionContractError(f"{label} must be an object")
    _reject_unknown_keys(value, allowed, label)
    return value


def _unique_ids(items: Iterable[object], label: str) -> set[str]:
    values = [str(getattr(item, "id")) for item in items]
    if len(set(values)) != len(values):
        raise TaskDirectionContractError(f"{label} contains duplicate ids")
    return set(values)


def _identifier(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise TaskDirectionContractError(
            f"{field_name} must match {_ID_RE.pattern}"
        )
    return text


def _required_text(value: object, field_name: str, max_chars: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TaskDirectionContractError(f"{field_name} must be a non-empty string")
    text = value.strip()
    if len(text) > max_chars:
        raise TaskDirectionContractError(f"{field_name} cannot exceed {max_chars} characters")
    return text


def _enum(value: object, field_name: str, allowed: set[str]) -> str:
    text = str(value or "").strip()
    if text not in allowed:
        raise TaskDirectionContractError(
            f"{field_name} must be one of: {', '.join(sorted(allowed))}"
        )
    return text


def _reject_unknown_keys(payload: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise TaskDirectionContractError(f"{label} has unknown fields: {', '.join(unknown)}")


def _item_payload(item: object) -> dict[str, Any]:
    payload = dict(vars(item))
    if "evidence_ids" in payload:
        payload["evidence_ids"] = list(payload["evidence_ids"])
    return payload
