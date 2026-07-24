from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tool.task_direction_tools import get_task_direction
from src.tool.task_direction_tools import replace_task_direction
from src.task_direction_context import CODE_TASK_PROTOCOL_CONTEXT
from src.task_direction_context import inject_task_direction_context
from src.task_direction_completion import TaskDirectionCompletion
from src.task_direction_models import TaskDirectionContractError
from src.task_direction_models import TaskDirectionState
from src.task_direction_store import TaskDirectionRevisionConflict
from src.task_direction_store import TaskDirectionStore
from src.task_direction_store import archive_legacy_task_artifacts


def _state(**overrides):
    payload = {
        "objective": "Analyze the repository and report evidence-backed architecture risks.",
        "hypotheses": [
            {
                "id": "h.runtime",
                "statement": "The runtime has an explicit orchestration boundary.",
                "status": "open",
                "evidence_ids": [],
            }
        ],
        "evidence": [],
        "unresolved_risks": [
            {
                "id": "r.tests",
                "severity": "P1",
                "statement": "The full suite has not been executed.",
                "status": "open",
                "evidence_ids": [],
            }
        ],
        "done_criteria": [
            {
                "id": "d.report",
                "statement": "Deliver an evidence-backed prioritized report.",
                "status": "pending",
                "evidence_ids": [],
            }
        ],
    }
    payload.update(overrides)
    return payload


class _Tools:
    function_map = {
        "get_task_direction": object(),
        "replace_task_direction": object(),
        "update_task_direction": object(),
    }


class _Agent:
    def __init__(self, memory_path, task_id="task-1"):
        self.current_memory_path = str(memory_path)
        self._agentpark_task_id = task_id
        self.tools = _Tools()
        self.messages = []

    def Message(self, role, content, persist=True):
        self.messages.append({"role": role, "content": content, "persist": persist})


def test_task_direction_store_uses_atomic_revision_contract(tmp_path):
    store = TaskDirectionStore(str(tmp_path / "task_direction.json"), task_id="task-1")
    first = store.replace(expected_revision=0, state=_state())
    second, _ = store.update(
        expected_revision=1,
        update={
            "evidence": [
                {
                    "id": "e.source",
                    "kind": "source",
                    "summary": "run_turn owns the loop",
                    "source": "src/runtime.py:10",
                }
            ],
            "hypotheses": [
                {
                    "id": "h.runtime",
                    "statement": "The runtime has an explicit orchestration boundary.",
                    "status": "confirmed",
                    "evidence_ids": ["e.source"],
                }
            ],
            "risks": [],
            "criteria": [],
        },
    )

    assert first.revision == 1
    assert first.task_id == "task-1"
    assert first.status == "active"
    assert second.revision == 2
    assert store.read().state.hypotheses[0].status == "confirmed"
    with pytest.raises(TaskDirectionRevisionConflict, match="expected 1, current 2"):
        store.update(
            expected_revision=1,
            update={
                "evidence": [
                    {
                        "id": "e.other",
                        "kind": "source",
                        "summary": "Other evidence.",
                        "source": "src/other.py:1",
                    }
                ],
                "hypotheses": [],
                "risks": [],
                "criteria": [],
            },
        )


def test_task_direction_full_replacement_is_rejected_after_initialization(tmp_path):
    store = TaskDirectionStore(str(tmp_path / "task_direction.json"), task_id="task-1")
    store.replace(expected_revision=0, state=_state())
    replacement = _state(
        evidence=[
            {
                "id": "e.source",
                "kind": "source",
                "summary": "run_turn owns the loop",
                "source": "src/runtime.py:10",
            }
        ],
        hypotheses=[
            {
                "id": "h.runtime",
                "statement": "The runtime has an explicit orchestration boundary.",
                "status": "confirmed",
                "evidence_ids": ["e.source"],
            }
        ],
    )

    with pytest.raises(TaskDirectionContractError, match="already initialized"):
        store.replace(expected_revision=1, state=replacement)


def test_task_direction_tools_round_trip_strict_state(tmp_path):
    agent = _Agent(tmp_path / "memory.md")
    created = json.loads(
        replace_task_direction(
            expected_revision=0,
            state=_state(),
            agent=agent,
        )
    )
    loaded = json.loads(get_task_direction(agent=agent))

    assert created["task_direction"]["revision"] == 1
    assert loaded == created


def test_task_direction_rejects_met_criterion_without_evidence(tmp_path):
    store = TaskDirectionStore(str(tmp_path / "task_direction.json"), task_id="task-1")
    invalid = _state(
        done_criteria=[
            {
                "id": "d.report",
                "statement": "Deliver report.",
                "status": "met",
                "evidence_ids": [],
            }
        ]
    )

    with pytest.raises(TaskDirectionContractError, match="evidence_ids is required"):
        store.replace(expected_revision=0, state=invalid)


def test_task_direction_rejects_unknown_evidence_reference(tmp_path):
    store = TaskDirectionStore(str(tmp_path / "task_direction.json"), task_id="task-1")
    invalid = _state(
        hypotheses=[
            {
                "id": "h.runtime",
                "statement": "Runtime boundary exists.",
                "status": "confirmed",
                "evidence_ids": ["e.missing"],
            }
        ]
    )

    with pytest.raises(TaskDirectionContractError, match="unknown evidence ids"):
        store.replace(expected_revision=0, state=invalid)


def test_task_direction_context_injects_protocol_and_saved_state(tmp_path):
    agent = _Agent(tmp_path / "memory.md")
    replace_task_direction(expected_revision=0, state=_state(), agent=agent)

    inject_task_direction_context(agent, role="developer")

    assert agent.messages[0] == {
        "role": "developer",
        "content": CODE_TASK_PROTOCOL_CONTEXT,
        "persist": False,
    }
    assert "<agentpark_task_direction" in agent.messages[1]["content"]
    assert '"revision": 1' in agent.messages[1]["content"]
    assert '"task_id": "task-1"' in agent.messages[1]["content"]


def test_task_direction_is_isolated_by_task_id_for_same_node_memory(tmp_path):
    first_agent = _Agent(tmp_path / "memory.md", task_id="task-1")
    second_agent = _Agent(tmp_path / "memory.md", task_id="task-2")
    replace_task_direction(expected_revision=0, state=_state(), agent=first_agent)

    inject_task_direction_context(second_agent, role="developer")

    assert len(second_agent.messages) == 1
    assert second_agent.messages[0]["content"] == CODE_TASK_PROTOCOL_CONTEXT
    assert TaskDirectionStore.for_agent(second_agent).read() is None
    assert TaskDirectionStore.for_agent(first_agent).path != TaskDirectionStore.for_agent(second_agent).path


def test_completed_task_direction_cannot_be_replaced(tmp_path):
    store = TaskDirectionStore(str(tmp_path / "task_direction.json"), task_id="task-1")
    first = store.replace(expected_revision=0, state=_state())
    completed = store.complete(expected_revision=first.revision)

    assert completed.status == "completed"
    assert completed.revision == 2
    with pytest.raises(TaskDirectionContractError, match="completed task direction"):
        store.replace(expected_revision=2, state=_state())


def test_task_direction_completion_merges_evidence_and_resolves_pending_ids():
    completion = TaskDirectionCompletion.from_payload(
        {
            "expected_revision": 3,
            "evidence": [
                {
                    "id": "e.final",
                    "kind": "test",
                    "summary": "Final verification passed.",
                    "source": "analysis_verification.json",
                }
            ],
            "hypotheses": [
                {
                    "id": "h.runtime",
                    "status": "confirmed",
                    "evidence_ids": ["e.final"],
                }
            ],
            "risks": [
                {
                    "id": "r.tests",
                    "status": "resolved",
                    "evidence_ids": ["e.final"],
                }
            ],
            "criteria": [
                {
                    "id": "d.report",
                    "status": "met",
                    "evidence_ids": ["e.final"],
                }
            ],
        },
        current_state=TaskDirectionState.from_payload(_state()),
    )

    assert completion.expected_revision == 3
    assert completion.state.evidence[0].id == "e.final"
    assert completion.state.hypotheses[0].status == "confirmed"
    assert completion.state.unresolved_risks[0].status == "resolved"
    assert completion.state.done_criteria[0].status == "met"


def test_task_direction_completion_unknown_id_error_lists_valid_ids():
    with pytest.raises(
        TaskDirectionContractError,
        match=r"unknown ids: r\.invented; valid ids: r\.tests",
    ):
        TaskDirectionCompletion.from_payload(
            {
                "expected_revision": 3,
                "evidence": [],
                "hypotheses": [],
                "risks": [
                    {
                        "id": "r.invented",
                        "status": "resolved",
                        "evidence_ids": [],
                    }
                ],
                "criteria": [
                    {
                        "id": "d.report",
                        "status": "met",
                        "evidence_ids": [],
                    }
                ],
            },
            current_state=TaskDirectionState.from_payload(_state()),
        )


def test_task_direction_completion_missing_criterion_error_lists_required_ids():
    with pytest.raises(
        TaskDirectionContractError,
        match=r"required pending ids: d\.report",
    ):
        TaskDirectionCompletion.from_payload(
            {
                "expected_revision": 3,
                "evidence": [],
                "hypotheses": [],
                "risks": [],
                "criteria": [],
            },
            current_state=TaskDirectionState.from_payload(_state()),
        )


def test_legacy_node_level_direction_and_analysis_artifacts_are_archived(tmp_path):
    legacy_direction = tmp_path / "task_direction.json"
    legacy_verification = tmp_path / "analysis_verification.json"
    legacy_direction.write_text('{"schema_version": 1}\n', encoding="utf-8")
    legacy_verification.write_text('{"run_id": "old"}\n', encoding="utf-8")

    moved = archive_legacy_task_artifacts(str(tmp_path))

    assert len(moved) == 2
    assert not legacy_direction.exists()
    assert not legacy_verification.exists()
    assert {Path(path).name for path in moved} == {
        "task_direction.json",
        "analysis_verification.json",
    }


def test_task_direction_context_skips_agents_without_capability(tmp_path):
    agent = _Agent(tmp_path / "memory.md")
    agent.tools.function_map = {}

    inject_task_direction_context(agent, role="system")

    assert agent.messages == []
