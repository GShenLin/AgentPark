from __future__ import annotations

import json

import pytest

from src.task_direction_models import TaskDirectionContractError
from src.task_direction_store import TaskDirectionRevisionConflict
from src.task_direction_store import TaskDirectionStore
from src.tool.task_direction_tools import replace_task_direction
from src.tool.task_direction_tools import update_task_direction


def _state() -> dict:
    return {
        "objective": "Complete the repository migration with verified boundaries.",
        "hypotheses": [
            {
                "id": "h.owner",
                "statement": "One module can own the canonical contract.",
                "status": "open",
                "evidence_ids": [],
            }
        ],
        "evidence": [],
        "unresolved_risks": [
            {
                "id": "r.boundary",
                "severity": "P1",
                "statement": "Boundary ownership is not traced.",
                "status": "open",
                "evidence_ids": [],
            }
        ],
        "done_criteria": [
            {
                "id": "c.tests",
                "statement": "Focused and full tests are recorded.",
                "status": "pending",
                "evidence_ids": [],
            }
        ],
    }


def _update(**overrides) -> dict:
    payload = {
        "evidence": [
            {
                "id": "e.trace",
                "kind": "source",
                "summary": "The route delegates serialization to the contract.",
                "source": "src/api.py:20",
            }
        ],
        "hypotheses": [
            {
                "id": "h.owner",
                "statement": "One module can own the canonical contract.",
                "status": "confirmed",
                "evidence_ids": ["e.trace"],
            }
        ],
        "risks": [
            {
                "id": "r.boundary",
                "severity": "P1",
                "statement": "Boundary ownership is not traced.",
                "status": "resolved",
                "evidence_ids": ["e.trace"],
            }
        ],
        "criteria": [],
    }
    payload.update(overrides)
    return payload


class _Agent:
    def __init__(self, memory_path):
        self.current_memory_path = str(memory_path)
        self._agentpark_task_id = "task-1"


def test_store_update_appends_evidence_and_changes_only_selected_items(tmp_path):
    store = TaskDirectionStore(str(tmp_path / "task_direction.json"), task_id="task-1")
    store.replace(expected_revision=0, state=_state())

    stored, applied = store.update(expected_revision=1, update=_update())

    assert stored.revision == 2
    assert stored.state.hypotheses[0].status == "confirmed"
    assert stored.state.unresolved_risks[0].status == "resolved"
    assert stored.state.done_criteria[0].status == "pending"
    assert applied.added_evidence_ids == ("e.trace",)
    assert applied.changed_hypothesis_ids == ("h.owner",)
    assert applied.changed_risk_ids == ("r.boundary",)
    assert applied.changed_criterion_ids == ()


def test_update_tool_returns_compact_receipt_instead_of_full_state(tmp_path):
    agent = _Agent(tmp_path / "memory.md")
    replace_task_direction(expected_revision=0, state=_state(), agent=agent)

    result = json.loads(
        update_task_direction(
            expected_revision=1,
            agent=agent,
            **_update(),
        )
    )

    assert result == {
        "status": "success",
        "task_id": "task-1",
        "revision": 2,
        "added_evidence_ids": ["e.trace"],
        "changed_ids": {
            "hypotheses": ["h.owner"],
            "risks": ["r.boundary"],
            "criteria": [],
        },
        "state_counts": {
            "hypotheses": 1,
            "evidence": 1,
            "risks": 1,
            "criteria": 1,
        },
    }
    assert "task_direction" not in result


def test_update_can_add_new_risk_and_criterion_with_new_evidence(tmp_path):
    store = TaskDirectionStore(str(tmp_path / "task_direction.json"), task_id="task-1")
    store.replace(expected_revision=0, state=_state())
    update = _update(
        hypotheses=[],
        risks=[
            {
                "id": "r.new",
                "severity": "P2",
                "statement": "A new integration boundary needs verification.",
                "status": "open",
                "evidence_ids": ["e.trace"],
            }
        ],
        criteria=[
            {
                "id": "c.new",
                "statement": "The new boundary has a focused test.",
                "status": "pending",
                "evidence_ids": ["e.trace"],
            }
        ],
    )

    stored, _ = store.update(expected_revision=1, update=update)

    assert [item.id for item in stored.state.unresolved_risks] == ["r.boundary", "r.new"]
    assert [item.id for item in stored.state.done_criteria] == ["c.tests", "c.new"]


def test_update_rejects_evidence_collision_and_statement_mutation(tmp_path):
    store = TaskDirectionStore(str(tmp_path / "task_direction.json"), task_id="task-1")
    store.replace(expected_revision=0, state=_state())
    store.update(expected_revision=1, update=_update())

    with pytest.raises(TaskDirectionContractError, match="reuses existing ids: e.trace"):
        store.update(
            expected_revision=2,
            update=_update(hypotheses=[], risks=[]),
        )

    with pytest.raises(TaskDirectionContractError, match="statement cannot change"):
        store.update(
            expected_revision=2,
            update={
                "evidence": [],
                "hypotheses": [
                    {
                        "id": "h.owner",
                        "statement": "Changed statement.",
                        "status": "confirmed",
                        "evidence_ids": ["e.trace"],
                    }
                ],
                "risks": [],
                "criteria": [],
            },
        )


def test_update_rejects_noop_terminal_regression_and_stale_revision(tmp_path):
    store = TaskDirectionStore(str(tmp_path / "task_direction.json"), task_id="task-1")
    store.replace(expected_revision=0, state=_state())
    store.update(expected_revision=1, update=_update())

    with pytest.raises(TaskDirectionContractError, match="does not change existing id h.owner"):
        store.update(
            expected_revision=2,
            update={
                "evidence": [],
                "hypotheses": [
                    {
                        "id": "h.owner",
                        "statement": "One module can own the canonical contract.",
                        "status": "confirmed",
                        "evidence_ids": ["e.trace"],
                    }
                ],
                "risks": [],
                "criteria": [],
            },
        )

    with pytest.raises(TaskDirectionContractError, match="cannot change terminal status confirmed"):
        store.update(
            expected_revision=2,
            update={
                "evidence": [],
                "hypotheses": [
                    {
                        "id": "h.owner",
                        "statement": "One module can own the canonical contract.",
                        "status": "rejected",
                        "evidence_ids": ["e.trace"],
                    }
                ],
                "risks": [],
                "criteria": [],
            },
        )

    with pytest.raises(TaskDirectionRevisionConflict, match="expected 1, current 2"):
        store.update(expected_revision=1, update=_update(evidence=[], hypotheses=[], risks=[]))


def test_update_requires_initialized_active_state_and_a_real_change(tmp_path):
    store = TaskDirectionStore(str(tmp_path / "task_direction.json"), task_id="task-1")
    with pytest.raises(TaskDirectionContractError, match="must be initialized"):
        store.update(expected_revision=1, update=_update())

    created = store.replace(expected_revision=0, state=_state())
    with pytest.raises(TaskDirectionContractError, match="at least one change"):
        store.update(
            expected_revision=created.revision,
            update={"evidence": [], "hypotheses": [], "risks": [], "criteria": []},
        )

    completed = store.complete(expected_revision=created.revision)
    with pytest.raises(TaskDirectionContractError, match="completed task direction"):
        store.update(expected_revision=completed.revision, update=_update())
