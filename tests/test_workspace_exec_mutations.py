from __future__ import annotations

import json

import pytest

from src.task_direction_store import TaskDirectionStore
from src.task_direction_store import TaskDirectionRevisionConflict
from src.tool.workspace_exec_tools import workspace_exec
from src.workspace_execution import WorkspaceExecutionContractError
from src.workspace_patch_requirements import WorkspacePatchRequirementError


def _state() -> dict:
    return {
        "objective": "Implement and verify the next repository stage.",
        "hypotheses": [
            {
                "id": "h.stage",
                "statement": "The stage boundary is understood.",
                "status": "open",
                "evidence_ids": [],
            }
        ],
        "evidence": [],
        "unresolved_risks": [],
        "done_criteria": [
            {
                "id": "c.done",
                "statement": "The implementation is verified.",
                "status": "pending",
                "evidence_ids": [],
            }
        ],
    }


def _update_arguments(expected_revision: int = 1) -> dict:
    return {
        "expected_revision": expected_revision,
        "evidence": [
            {
                "id": "e.stage1",
                "kind": "test",
                "summary": "Stage 1 focused tests passed.",
                "source": "pytest stage1",
            }
        ],
        "hypotheses": [
            {
                "id": "h.stage",
                "statement": "The stage boundary is understood.",
                "status": "confirmed",
                "evidence_ids": ["e.stage1"],
            }
        ],
        "risks": [],
        "criteria": [],
    }


class _Agent:
    def __init__(self, memory_path):
        self.current_memory_path = str(memory_path)
        self._agentpark_task_id = "task-1"
        self.config = {}


def test_workspace_exec_sequences_direction_update_before_patch(tmp_path):
    agent = _Agent(tmp_path / "node" / "memory.md")
    store = TaskDirectionStore.for_agent(agent)
    store.replace(expected_revision=0, state=_state())
    target = tmp_path / "workspace" / "value.txt"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")

    result = json.loads(
        workspace_exec(
            [
                {
                    "id": "persist_stage1",
                    "operations": [
                        {
                            "id": "direction",
                            "kind": "update_task_direction",
                            "arguments": _update_arguments(),
                        }
                    ],
                },
                {
                    "id": "apply_stage2",
                    "operations": [
                        {
                            "id": "patch",
                            "kind": "apply_patch",
                            "arguments": {
                                "patch": (
                                    "*** Begin Patch\n"
                                    f"*** Update File: {target}\n"
                                    "@@\n"
                                    "-before\n"
                                    "+after\n"
                                    "*** End Patch\n"
                                ),
                                "required_changes": [
                                    {
                                        "id": "replace_value",
                                        "kind": "replacement",
                                        "old_text": "before",
                                        "new_text": "after",
                                    }
                                ],
                            },
                        }
                    ],
                },
            ],
            context_checkpoint="retain_until_next_handoff",
            agent=agent,
        )
    )

    assert result["status"] == "success"
    assert result["stage_count"] == 2
    assert result["operation_count"] == 2
    assert store.read().revision == 2
    assert store.read().state.hypotheses[0].status == "confirmed"
    assert target.read_text(encoding="utf-8") == "after\n"


def test_workspace_exec_stops_before_patch_when_direction_stage_fails(tmp_path):
    agent = _Agent(tmp_path / "node" / "memory.md")
    store = TaskDirectionStore.for_agent(agent)
    store.replace(expected_revision=0, state=_state())
    target = tmp_path / "workspace" / "value.txt"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")

    with pytest.raises(TaskDirectionRevisionConflict, match="revision conflict"):
        workspace_exec(
            [
                {
                    "id": "persist_stage1",
                    "operations": [
                        {
                            "id": "direction",
                            "kind": "update_task_direction",
                            "arguments": _update_arguments(expected_revision=2),
                        }
                    ],
                },
                {
                    "id": "apply_stage2",
                    "operations": [
                        {
                            "id": "patch",
                            "kind": "apply_patch",
                            "arguments": {
                                "patch": (
                                    "*** Begin Patch\n"
                                    f"*** Update File: {target}\n"
                                    "@@\n"
                                    "-before\n"
                                    "+after\n"
                                    "*** End Patch\n"
                                ),
                                "required_changes": [
                                    {
                                        "id": "replace_value",
                                        "kind": "replacement",
                                        "old_text": "before",
                                        "new_text": "after",
                                    }
                                ],
                            },
                        }
                    ],
                },
            ],
            context_checkpoint="retain_until_next_handoff",
            agent=agent,
        )

    assert target.read_text(encoding="utf-8") == "before\n"


def test_workspace_exec_checks_patch_requirements_before_mutation(tmp_path):
    agent = _Agent(tmp_path / "node" / "memory.md")
    target = tmp_path / "workspace" / "value.txt"
    target.parent.mkdir(parents=True)
    target.write_text("before\n", encoding="utf-8")

    with pytest.raises(WorkspacePatchRequirementError, match="old_text removal"):
        workspace_exec(
            [
                {
                    "id": "apply",
                    "operations": [
                        {
                            "id": "patch",
                            "kind": "apply_patch",
                            "arguments": {
                                "patch": (
                                    "*** Begin Patch\n"
                                    f"*** Update File: {target}\n"
                                    "@@\n"
                                    "-before\n"
                                    "+after\n"
                                    "*** End Patch\n"
                                ),
                                "required_changes": [
                                    {
                                        "id": "wrong_obligation",
                                        "kind": "replacement",
                                        "old_text": "not present",
                                        "new_text": "after",
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
            agent=agent,
        )

    assert target.read_text(encoding="utf-8") == "before\n"


def test_workspace_exec_requires_mutations_in_exclusive_stages(tmp_path):
    agent = _Agent(tmp_path / "node" / "memory.md")

    with pytest.raises(WorkspaceExecutionContractError, match="exclusive stage"):
        workspace_exec(
            [
                {
                    "id": "invalid",
                    "operations": [
                        {
                            "id": "direction",
                            "kind": "update_task_direction",
                            "arguments": _update_arguments(),
                        },
                        {
                            "id": "read",
                            "kind": "read_file",
                            "arguments": {"file_path": "README.md"},
                        },
                    ],
                }
            ],
            agent=agent,
        )


def test_workspace_exec_does_not_run_later_stage_after_error_result(monkeypatch):
    import src.workspace_execution as execution

    calls = []
    monkeypatch.setattr(
        execution,
        "execute_console_command",
        lambda **_kwargs: json.dumps({"status": "error", "error": "failed"}),
    )
    monkeypatch.setattr(
        execution,
        "read_file",
        lambda **_kwargs: calls.append("read") or json.dumps({"status": "success"}),
    )

    result = json.loads(
        workspace_exec(
            [
                {
                    "id": "failing",
                    "operations": [
                        {
                            "id": "command",
                            "kind": "run_command",
                            "arguments": {"command": "exit 1"},
                        }
                    ],
                },
                {
                    "id": "must_not_run",
                    "operations": [
                        {
                            "id": "read",
                            "kind": "read_file",
                            "arguments": {"file_path": "README.md"},
                        }
                    ],
                },
            ],
            agent=type("Agent", (), {"config": {}})(),
        )
    )

    assert result["status"] == "error"
    assert result["stage_count"] == 1
    assert result["operation_count"] == 1
    assert calls == []
