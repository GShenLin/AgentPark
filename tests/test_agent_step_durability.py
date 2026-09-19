from __future__ import annotations

import pytest

from src.agent_step_ledger import AgentStepLedger
from src.agent_step_ledger import TOOL_OUTCOME_UNKNOWN
from src.base_agent import BaseAgent
from src.tool.tool_call_protocol import ToolCallEnvelope


class _Agent(BaseAgent):
    def Send(self, *args, **kwargs):
        _ = args, kwargs
        return ""


def _config(**overrides):
    config = {
        "model": "deepseek-v4-pro",
        "agentStepLedgerEnabled": True,
        "sessionContextCompactionEnabled": True,
        "sessionContextCompactionThresholdPercent": 80,
        "sessionContextCompactionRetainPercent": 16,
        "modelContextWindowTokens": 200,
        "toolContextCompactionEnabled": False,
        "toolResultSubmissionMaxChars": 50000,
        "responsesApi": True,
        "responsesReplayReasoningItems": False,
    }
    config.update(overrides)
    return config


def _agent(tmp_path, **config):
    agent = _Agent("deepseek_test", memory_file_path=str(tmp_path / "memory.md"))
    agent.config = _config(**config)
    return agent


def test_step_ledger_materializes_only_unmatched_tool_starts(tmp_path):
    ledger = AgentStepLedger(str(tmp_path / "agent_steps.jsonl"))
    ledger.append(
        "tool_call_started",
        step_id="step-1",
        call_id="call-unknown",
        tool="write_file",
        arguments={"path": "state.txt"},
    )
    ledger.append(
        "tool_call_started",
        step_id="step-1",
        call_id="call-finished",
        tool="read_file",
        arguments={"path": "state.txt"},
    )
    ledger.append(
        "tool_call_finished",
        step_id="step-1",
        call_id="call-finished",
        tool="read_file",
        status="completed",
    )

    outcomes = ledger.unknown_tool_outcomes()

    assert [item.call_id for item in outcomes] == ["call-unknown"]
    assert outcomes[0].to_payload()["code"] == TOOL_OUTCOME_UNKNOWN
    assert "verify the external state" in outcomes[0].to_payload()["instruction"]


def test_unknown_tool_outcome_is_injected_as_model_visible_recovery_context(tmp_path):
    agent = _agent(tmp_path)
    ledger = agent._agent_step_ledger()
    ledger.append(
        "tool_call_started",
        step_id="step-crashed",
        call_id="call-side-effect",
        tool="shell_command",
        arguments={"command": "publish"},
    )
    agent.Message("user", "continue after recovery", persist=False)

    payloads = agent._inject_unknown_tool_outcomes()

    assert payloads[0]["code"] == TOOL_OUTCOME_UNKNOWN
    assert payloads[0]["call_id"] == "call-side-effect"
    assert [message["role"] for message in agent.messages] == ["assistant", "tool", "user"]
    assert agent.messages[0]["tool_calls"][0]["id"] == "call-side-effect"
    assert TOOL_OUTCOME_UNKNOWN in agent.messages[1]["content"]
    assert "verify the external state first" in agent.messages[1]["content"]
    assert agent.messages[-1]["content"] == "continue after recovery"
    assert agent._agent_step_ledger().read()[-1]["event"] == "tool_outcome_recovered"


def test_unknown_tool_recovery_is_reconstructed_without_duplicate_recovery_events(tmp_path):
    first = _agent(tmp_path)
    first._agent_step_ledger().append(
        "tool_call_started",
        step_id="step-crashed",
        call_id="call-recover-on-resume",
        tool="publish_release",
        arguments={"target": "staging"},
    )
    first._inject_unknown_tool_outcomes()

    resumed = _agent(tmp_path)
    resumed.Message("user", "resume", persist=False)
    resumed._inject_unknown_tool_outcomes()

    assert [message["role"] for message in resumed.messages] == ["assistant", "tool", "user"]
    assert resumed.messages[0]["tool_calls"][0]["id"] == "call-recover-on-resume"
    events = resumed._agent_step_ledger().read()
    assert sum(event["event"] == "tool_outcome_recovered" for event in events) == 1


def test_new_provider_request_closes_interrupted_step_before_starting_another(tmp_path):
    first = _agent(tmp_path)
    first._agent_step_ledger().append(
        "provider_request_started",
        step_id="interrupted-step",
        request_id="interrupted-request",
        request_api="responses",
    )

    resumed = _agent(tmp_path)
    new_step = resumed._checkpoint_provider_request(request_api="responses")
    events = resumed._agent_step_ledger().read()

    assert events[-2]["event"] == "step_closed"
    assert events[-2]["step_id"] == "interrupted-step"
    assert events[-2]["reason"] == "process_recovered"
    assert events[-1]["event"] == "provider_request_started"
    assert events[-1]["step_id"] == new_step


def test_tool_body_runs_only_after_durable_start_checkpoint(tmp_path):
    agent = _agent(tmp_path, sessionContextCompactionEnabled=False)
    observed = []

    def tool(value, agent=None):
        _ = agent
        observed.append(value)
        events = agent_instance._agent_step_ledger().read()
        assert events[-1]["event"] == "tool_call_started"
        return {"ok": True}

    agent_instance = agent
    agent.tools.function_map["write_once"] = tool
    call = ToolCallEnvelope(
        name="write_once",
        call_id="call-1",
        arguments={"value": "done"},
        arguments_json='{"value":"done"}',
        provider="deepseek",
    )

    execution = agent.tools.execute_tool_call(call)

    assert observed == ["done"]
    assert execution.status == "completed"
    events = agent._agent_step_ledger().read()
    assert [item["event"] for item in events] == ["tool_call_started", "tool_call_finished"]


def test_tool_execution_fails_closed_when_start_checkpoint_cannot_persist(tmp_path, monkeypatch):
    agent = _agent(tmp_path, sessionContextCompactionEnabled=False)
    observed = []
    agent.tools.function_map["write_once"] = lambda value, agent=None: observed.append(value)
    call = ToolCallEnvelope(
        name="write_once",
        call_id="call-start-failed",
        arguments={"value": "must-not-run"},
        arguments_json='{"value":"must-not-run"}',
        provider="deepseek",
    )
    monkeypatch.setattr(
        agent,
        "_record_tool_call_started",
        lambda _call: (_ for _ in ()).throw(OSError("ledger unavailable")),
    )

    with pytest.raises(OSError, match="ledger unavailable"):
        agent.tools.execute_tool_call(call)

    assert observed == []


def test_missing_finish_checkpoint_becomes_unknown_outcome(tmp_path, monkeypatch):
    agent = _agent(tmp_path, sessionContextCompactionEnabled=False)
    agent.tools.function_map["write_once"] = lambda value, agent=None: {"written": value}
    call = ToolCallEnvelope(
        name="write_once",
        call_id="call-finish-failed",
        arguments={"value": "possibly-written"},
        arguments_json='{"value":"possibly-written"}',
        provider="deepseek",
    )
    monkeypatch.setattr(
        agent,
        "_record_tool_call_finished",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("finish unavailable")),
    )

    with pytest.raises(OSError, match="finish unavailable"):
        agent.tools.execute_tool_call(call)

    outcomes = agent._agent_step_ledger().unknown_tool_outcomes()
    assert [item.call_id for item in outcomes] == ["call-finish-failed"]


def test_chat_provider_request_and_final_step_are_durable(tmp_path):
    from src.providers.deepseek_agent import DeepSeekAgent

    agent = DeepSeekAgent(
        provider_id="deepseek_v4_pro",
        memory_file_path=str(tmp_path / "memory.md"),
        internal_memory_enabled=False,
    )
    agent.config = _config(
        responsesApi=False,
        sessionContextCompactionEnabled=False,
        type="deepseek",
        apiKey="test-key",
        baseUrl="https://api.deepseek.test",
        thinking="disabled",
        maxRetries=0,
        retryDelaySec=0,
    )
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent.Message("user", "hello", persist=False)
    agent._curl_post_json_once = lambda **_kwargs: {
        "choices": [{"message": {"role": "assistant", "content": "done"}}]
    }

    assert agent.Send(run_tools=True, stream=False) == "done"

    events = agent._agent_step_ledger().read()
    assert [item["event"] for item in events] == [
        "provider_request_started",
        "provider_response_received",
        "step_closed",
    ]
    assert events[0]["step_id"] == events[1]["step_id"] == events[2]["step_id"]
