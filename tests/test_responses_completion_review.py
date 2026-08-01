from types import SimpleNamespace

from src.providers.responses_completion_review import ResponsesCompletionReview
from src.runtime_policy import resolve_runtime_policy


COMPLETION_REVIEW_INSTRUCTION = resolve_runtime_policy(None).policy.completion_review.prompt


def _runtime():
    messages = [{"role": "user", "content": "fix the startup path"}]
    return SimpleNamespace(
        messages=messages,
        RuntimeInstructionMessage=lambda content: {
            "role": "developer",
            "content": content,
        },
    )


def _review(
    *,
    enabled=True,
    passes=1,
    require_tool_executions=True,
    require_done_criteria=False,
    require_resolved_risks=False,
):
    return ResponsesCompletionReview(
        enabled=enabled,
        max_passes=passes,
        require_tool_executions=require_tool_executions,
        require_done_criteria=require_done_criteria,
        require_resolved_risks=require_resolved_risks,
        prompt=COMPLETION_REVIEW_INSTRUCTION,
    )


def test_default_runtime_policy_disables_completion_gate():
    assert resolve_runtime_policy(None).policy.completion_review.enabled is False


def test_completion_review_stops_after_initial_pass_when_contract_is_closed():
    runtime = _runtime()
    review = _review(passes=2)

    assert review.start_if_needed(
        runtime,
        draft_text="implemented",
        had_regular_tool_executions=True,
    )
    assert runtime.messages[-2] == {"role": "assistant", "content": "implemented"}
    assert runtime.messages[-1]["content"] == COMPLETION_REVIEW_INSTRUCTION
    assert not review.start_if_needed(
        runtime,
        draft_text="implemented again",
        had_regular_tool_executions=True,
    )
    assert len(runtime.messages) == 3
    assert not review.start_if_needed(
        runtime,
        draft_text="implemented a third time",
        had_regular_tool_executions=True,
    )

    review.finish(runtime)

    assert runtime.messages == [{"role": "user", "content": "fix the startup path"}]


def test_completion_review_skips_non_mutating_or_empty_turns():
    runtime = _runtime()
    review = _review()

    assert not review.start_if_needed(
        runtime,
        draft_text="",
        had_regular_tool_executions=True,
    )
    assert not review.start_if_needed(
        runtime,
        draft_text="answer only",
        had_regular_tool_executions=False,
    )
    assert len(runtime.messages) == 1


def test_completion_review_can_review_a_tool_free_turn_when_policy_allows_it():
    runtime = _runtime()
    review = _review(require_tool_executions=False)

    assert review.start_if_needed(
        runtime,
        draft_text="analysis answer",
        had_regular_tool_executions=False,
    )


def test_completion_review_releases_task_direction_criteria_after_review_budget(
    tmp_path,
):
    from src.task_direction_store import TaskDirectionStore

    memory_path = tmp_path / "memory.md"
    memory_path.write_text("", encoding="utf-8")
    runtime = _runtime()
    runtime.current_memory_path = str(memory_path)
    runtime._agentpark_task_id = "criteria-review"
    TaskDirectionStore.for_agent(runtime).replace(
        expected_revision=0,
        state={
            "objective": "Complete every named surface.",
            "hypotheses": [],
            "evidence": [],
            "unresolved_risks": [
                {
                    "id": "R1",
                    "severity": "P1",
                    "statement": "Settings UI may remain configurable.",
                    "status": "open",
                    "evidence_ids": [],
                }
            ],
            "done_criteria": [
                {
                    "id": "C1",
                    "statement": "Settings UI is no longer configurable.",
                    "status": "pending",
                    "evidence_ids": [],
                }
            ],
        },
    )
    review = _review(
        passes=2,
        require_done_criteria=True,
        require_resolved_risks=True,
    )

    assert review.start_if_needed(
        runtime,
        draft_text="first draft",
        had_regular_tool_executions=True,
    )
    assert "criterion C1 is pending" in runtime.messages[-1]["content"]
    assert "risk R1 is open" in runtime.messages[-1]["content"]
    assert review.start_if_needed(
        runtime,
        draft_text="second draft",
        had_regular_tool_executions=True,
    )
    assert not review.start_if_needed(
        runtime,
        draft_text="third draft",
        had_regular_tool_executions=True,
    )

    review.finish(runtime)

    assert runtime.messages == [{"role": "user", "content": "fix the startup path"}]
