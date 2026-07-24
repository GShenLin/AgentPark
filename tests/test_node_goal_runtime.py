import json
import threading

import pytest

from src.message_protocol import build_text_envelope
from src.web_backend.node_goal_runtime import GoalEvaluationError
from src.web_backend.node_goal_runtime import NodeGoalRuntime
from src.web_backend.node_goal_runtime import has_structured_completion_audit
from src.web_backend.node_goal_runtime import node_goal_context
from src.web_backend.node_goal_runtime import parse_goal_evaluation
from src.web_backend.state_store import _read_json_dict, _write_json_dict


def test_parse_goal_evaluation_accepts_structured_result():
    result = parse_goal_evaluation(
        '{"new_goal_state":"complete","reason":"The assistant output satisfies every requested item."}'
    )

    assert result == {
        "new_goal_state": "complete",
        "reason": "The assistant output satisfies every requested item.",
    }


def test_parse_goal_evaluation_rejects_missing_reason():
    with pytest.raises(GoalEvaluationError, match="reason"):
        parse_goal_evaluation('{"new_goal_state":"active"}')


def test_parse_goal_evaluation_rejects_extra_fields():
    with pytest.raises(GoalEvaluationError, match="exactly"):
        parse_goal_evaluation('{"new_goal_state":"active","reason":"more work","status":"active"}')


def test_parse_goal_evaluation_rejects_wrapped_json():
    with pytest.raises(GoalEvaluationError, match="valid JSON"):
        parse_goal_evaluation('```json\n{"new_goal_state":"active","reason":"more work"}\n```')


def test_node_goal_context_only_renders_active_goal():
    active = node_goal_context(
        {
            "goal": "ship the workflow",
            "goal_state": {"status": "active", "reason": "started"},
        }
    )
    complete = node_goal_context(
        {
            "goal": "ship the workflow",
            "goal_state": {"status": "complete", "reason": "done"},
        }
    )

    assert "ship the workflow" in active
    assert active.startswith('<agentpark_internal_context source="goal">\n')
    assert "<objective>\nship the workflow\n</objective>" in active
    assert "Goal completion audit:" in active
    assert active.endswith("</agentpark_internal_context>")
    assert complete == ""


def test_goal_evaluator_prompt_requires_executor_completion_audit():
    prompt = NodeGoalRuntime._goal_evaluator_system_prompt()
    user_prompt = NodeGoalRuntime._goal_evaluator_user_prompt(
        goal="improve project structure",
        state={"status": "active"},
        input_message=build_text_envelope("start", role="user"),
        output_message=build_text_envelope("split one module and tests passed", role="assistant"),
    )

    assert "executor's own completion audit" in prompt
    assert "Goal completion audit:" in prompt
    assert "Do not infer completion from useful progress" in prompt
    assert "Known caveats: none" in prompt
    assert "Remaining required work: none" in prompt
    assert "full-goal completion audit" in user_prompt


class _FakeCore:
    runtime_owner_id = "test-owner"


class _FakeHost:
    def __init__(self):
        self.core = _FakeCore()
        self.events = []
        self.ensure_graph_runner_calls = []

    def _log_graph_event(self, graph_id, event, **payload):
        self.events.append((graph_id, event, payload))

    def _ensure_graph_runner(self, graph_id):
        self.ensure_graph_runner_calls.append(graph_id)

    def _wake_graph_runner(self, graph_id):
        self.ensure_graph_runner_calls.append(f"wake:{graph_id}")


class _FakeGoalRuntime(NodeGoalRuntime):
    def __init__(self, host, evaluation):
        super().__init__(host)
        self.evaluation = evaluation

    def _run_goal_evaluator(self, **_kwargs):
        return dict(self.evaluation)


class _FailingGoalRuntime(NodeGoalRuntime):
    def _run_goal_evaluator(self, **_kwargs):
        raise AssertionError("goal evaluator should not run")


def _write_goal_config(tmp_path, *, status="active"):
    config_path = tmp_path / "node.json"
    _write_json_dict(
        str(config_path),
        {
            "schemaVersion": 1,
            "node_id": "n1",
            "graph_id": "g1",
            "type_id": "agent_node",
            "provider_id": "fake-provider",
            "goal": "finish the workflow",
            "goal_state": {
                "status": status,
                "reason": "started",
                "turn_count": 1,
            },
            "pending": [],
        },
    )
    return config_path


def _read_runtime_state(config_path):
    return _read_json_dict(str(config_path))


def _structured_completion_audit() -> str:
    return (
        "All requested work is done.\n\n"
        "Goal completion audit:\n"
        "Original goal: finish the workflow\n"
        "Current-state evidence: the current workflow output and persisted project state satisfy every requested item.\n"
        "Verification evidence: targeted checks passed and the final output was persisted.\n"
        "Known caveats: none\n"
        "Remaining required work: none"
    )


def test_node_goal_runtime_persists_active_state_and_enqueues_continuation(tmp_path):
    config_path = _write_goal_config(tmp_path)
    host = _FakeHost()
    runtime = _FakeGoalRuntime(host, {"new_goal_state": "active", "reason": "continue with step two"})
    wake_event = threading.Event()
    output_message = build_text_envelope(_structured_completion_audit(), role="assistant")

    result = runtime._evaluate_node_goal_after_persist(
        graph_id="g1",
        node_id="n1",
        node_type_id="agent_node",
        config_path=str(config_path),
        config={},
        input_message=build_text_envelope("start", role="user"),
        output_message=output_message,
        trace_id="trace-1",
        depth=0,
        wake_event=wake_event,
    )

    saved = _read_runtime_state(config_path)
    assert result["should_continue"] is True
    assert saved["goal_state"]["status"] == "active"
    assert saved["goal_state"]["reason"] == "continue with step two"
    assert saved["goal_state"]["turn_count"] == 2
    assert saved["pending"][0]["source"] == "goal_continuation"
    assert saved["pending"][0]["payload"]["role"] == "user"
    assert "Goal completion audit:" in saved["pending"][0]["payload"]["parts"][0]["text"]
    assert wake_event.is_set()
    assert host.ensure_graph_runner_calls == ["g1"]


def test_node_goal_runtime_keeps_active_without_structured_completion_audit(tmp_path):
    config_path = _write_goal_config(tmp_path)
    host = _FakeHost()
    runtime = _FailingGoalRuntime(host)
    wake_event = threading.Event()

    result = runtime._evaluate_node_goal_after_persist(
        graph_id="g1",
        node_id="n1",
        node_type_id="agent_node",
        config_path=str(config_path),
        config={},
        input_message=build_text_envelope("start", role="user"),
        output_message=build_text_envelope(
            "Goal completion audit:\nThe full goal is complete and no required work remains.",
            role="assistant",
        ),
        trace_id="trace-1",
        depth=0,
        wake_event=wake_event,
    )

    saved = _read_runtime_state(config_path)
    assert result["should_continue"] is True
    assert saved["goal_state"]["status"] == "active"
    assert saved["goal_state"]["reason"] == "executor did not provide the required structured full-goal completion audit"
    assert saved["pending"][0]["source"] == "goal_continuation"
    assert wake_event.is_set()


def test_node_goal_runtime_persists_complete_state_without_continuation(tmp_path):
    config_path = _write_goal_config(tmp_path)
    host = _FakeHost()
    runtime = _FakeGoalRuntime(host, {"new_goal_state": "complete", "reason": "all requested work is done"})
    wake_event = threading.Event()
    output_message = build_text_envelope(_structured_completion_audit(), role="assistant")

    assert has_structured_completion_audit(output_message) is True

    result = runtime._evaluate_node_goal_after_persist(
        graph_id="g1",
        node_id="n1",
        node_type_id="agent_node",
        config_path=str(config_path),
        config={},
        input_message=build_text_envelope("start", role="user"),
        output_message=output_message,
        trace_id="trace-1",
        depth=0,
        wake_event=wake_event,
    )

    saved = _read_runtime_state(config_path)
    assert result["should_continue"] is False
    assert saved["goal_state"]["status"] == "complete"
    assert saved["goal_state"]["reason"] == "all requested work is done"
    assert saved["pending"] == []
    assert not wake_event.is_set()
