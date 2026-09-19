from __future__ import annotations

import json

from src.base_agent import BaseAgent
from src.session_context_compaction import SESSION_CONTEXT_CHECKPOINT_PREFIX
from src.tool.tool_call_protocol import ToolCallExecution


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
        "sessionContextCompactionMaxAttempts": 3,
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


def test_session_context_compaction_replaces_old_prefix_and_persists_checkpoint(tmp_path):
    agent = _agent(tmp_path)
    agent.Message("system", "system policy", persist=False)
    agent.Message("user", "old request " + "A" * 500, persist=False)
    agent.Message("assistant", "old answer " + "B" * 500, persist=False)
    agent.Message("user", "current request must remain", persist=False)

    started = agent._prepare_session_context_compaction_if_needed(
        [{"type": "function", "function": {"name": "read_file"}}]
    )

    assert started is True
    assert agent._session_context_compaction_active_tools([])[0]["function"]["name"] == "compact_session_context"
    result = agent._apply_session_context_compaction(
        reason="older prefix exceeds the full-session pressure threshold",
        summary={
            "task_anchor": "current request must remain",
            "completed_facts": ["old fact"],
            "changed_state": [],
            "verification": [],
            "failed_attempts": [],
            "remaining_steps": ["continue current request"],
            "immediate_next_step": "continue current request",
            "critical_context": ["preserve exact constraints"],
        },
    )
    completed = agent._session_context_compaction_gate_completed(
        [
            ToolCallExecution(
                func_name="compact_session_context",
                call_id="compact-1",
                cleaned_result=json.dumps(result),
                status="completed",
            )
        ]
    )

    assert completed is True
    assert any(
        str(message.get("content") or "").startswith(SESSION_CONTEXT_CHECKPOINT_PREFIX)
        for message in agent.messages
        if isinstance(message, dict)
    )
    assert any(message.get("content") == "current request must remain" for message in agent.messages)
    assert not any(str(message.get("content") or "").startswith("old request") for message in agent.messages)
    checkpoint = agent._agent_step_ledger().latest_compaction_checkpoint()
    assert checkpoint["replaced_message_count"] == 2


def test_persisted_session_checkpoint_is_restored_by_new_agent_instance(tmp_path):
    first = _agent(tmp_path)
    first._agent_step_ledger().append(
        "session_context_compacted",
        reason="pressure",
        summary={"task_anchor": "resume"},
        checkpoint=f"{SESSION_CONTEXT_CHECKPOINT_PREFIX}\nresume exact work",
        replaced_message_count=4,
    )

    restored = _agent(tmp_path)
    restored.Message("user", "new input", persist=False)
    restored._restore_session_context_checkpoint()

    assert restored.messages[0]["content"].startswith(SESSION_CONTEXT_CHECKPOINT_PREFIX)
    assert restored.messages[1]["content"] == "new input"


def test_responses_compaction_retries_strict_schema_then_continues_normal_request(tmp_path):
    from src.providers.deepseek_agent import DeepSeekAgent

    agent = DeepSeekAgent(
        provider_id="deepseek_v4_pro",
        memory_file_path=str(tmp_path / "memory.md"),
        internal_memory_enabled=False,
    )
    agent.config = _config(
        type="deepseek",
        apiKey="test-key",
        baseUrl="https://api.deepseek.test",
        maxTokens=1024,
        thinking="enabled",
        reasoningEffort="high",
    )
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent.Message("user", "old request " + "A" * 600, persist=False)
    agent.Message("assistant", "old answer " + "B" * 600, persist=False)
    agent.Message("user", "finish the current request", persist=False)
    payloads = []
    summary = {
        "task_anchor": "finish the current request",
        "completed_facts": ["old work was inspected"],
        "changed_state": [],
        "verification": [],
        "failed_attempts": [],
        "remaining_steps": ["finish the current request"],
        "immediate_next_step": "finish the current request",
        "critical_context": ["do not repeat old work"],
    }

    def fake_post(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        payloads.append(payload)
        if len(payloads) == 1:
            invalid_summary = dict(summary)
            invalid_summary.pop("critical_context")
            return {
                "id": "resp-compact-invalid",
                "output": [{
                    "type": "function_call",
                    "call_id": "compact-call-invalid",
                    "name": "compact_session_context",
                    "arguments": json.dumps(
                        {"reason": "context pressure", "summary": invalid_summary},
                        ensure_ascii=False,
                    ),
                }],
            }
        if len(payloads) == 2:
            return {
                "id": "resp-compact",
                "output": [{
                    "type": "function_call",
                    "call_id": "compact-call",
                    "name": "compact_session_context",
                    "arguments": json.dumps(
                        {"reason": "context pressure", "summary": summary},
                        ensure_ascii=False,
                    ),
                }],
            }
        return {
            "id": "resp-final",
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": "finished after compaction"}],
            }],
        }

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    result = agent.Send(run_tools=True, stream=False, reasoning_effort="high")

    assert result == "finished after compaction"
    assert len(payloads) == 3
    for payload in payloads[:2]:
        assert payload["tool_choice"] == "required"
        assert [tool["name"] for tool in payload["tools"]] == ["compact_session_context"]
        assert payload["reasoning"]["effort"] == "none"
    assert "tools" not in payloads[2]
    assert payloads[2]["reasoning"]["effort"] == "high"
    events = agent._agent_step_ledger().read()
    assert sum(event["event"] == "session_context_compacted" for event in events) == 1
    provider_events = [
        event
        for event in events
        if event["event"] in {"provider_request_started", "provider_response_received", "step_closed"}
    ]
    assert [event["event"] for event in provider_events] == [
        "provider_request_started", "provider_response_received", "step_closed",
        "provider_request_started", "provider_response_received", "step_closed",
        "provider_request_started", "provider_response_received", "step_closed",
    ]
    assert len({event["step_id"] for event in provider_events}) == 3
    assert provider_events[0]["request_id"] != provider_events[3]["request_id"]
