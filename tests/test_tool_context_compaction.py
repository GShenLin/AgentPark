import copy
import json

import pytest

from src.base_agent import BaseAgent
from src.tool.tool_call_protocol import ToolCallExecution


def _checkpoint(fact, next_step="Continue the current task."):
    return {
        "task_anchor": "Complete the current task without repeating finished work.",
        "completed_facts": [fact],
        "changed_state": [],
        "verification": [],
        "failed_attempts": [],
        "remaining_steps": [next_step],
        "immediate_next_step": next_step,
        "avoid_repeating": [fact],
    }


class DummyCompactionAgent(BaseAgent):
    def __init__(self, memory_path):
        super().__init__("dummy", memory_file_path=str(memory_path), internal_memory_enabled=False)
        self.sent_tools = []
        self.last_gate_messages = []
        self.config = {
            "toolContextCompactionEnabled": True,
            "toolContextCompactionEveryToolCalls": 2,
            "toolContextCompactionInputTokens": 0,
            "toolContextCompactionCurrentInputTokens": 0,
            "toolContextCompactionOutputTokens": 0,
        }

    def Send(self, tools=None, run_tools=True, mode="chat", stream=False):
        self.last_gate_messages = list(self.messages)
        self.sent_tools.append(tools)
        result = self.tools.execute_tool(
            "compact_tool_context",
            {
                "action": "replace",
                "reason": "The tool window has been reviewed.",
                "summary": _checkpoint(
                    "Inspected alpha.py and beta.py; keep the beta.py finding."
                ),
            },
        )
        self.Message("tool", result, persist=False, tool_call_id="compact-gate", name="compact_tool_context")
        return result


class DummyUsageCompactionAgent(DummyCompactionAgent):
    def __init__(self, memory_path):
        super().__init__(memory_path)
        self.actual_input_tokens = 0
        self.actual_output_tokens = 0
        self.last_actual_input_tokens = 0
        self.compaction_input_tokens = 0
        self.compaction_output_tokens = 0

    def _provider_request_snapshot(self):
        return {
            "totals": {
                "actual_input_tokens": self.actual_input_tokens,
                "actual_output_tokens": self.actual_output_tokens,
                "last_actual_input_tokens": self.last_actual_input_tokens,
            }
        }

    def Send(self, tools=None, run_tools=True, mode="chat", stream=False):
        self.actual_input_tokens += self.compaction_input_tokens
        self.actual_output_tokens += self.compaction_output_tokens
        return super().Send(tools=tools, run_tools=run_tools, mode=mode, stream=stream)


def _tool_call_message(call_id, name):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }
        ],
    }


def _compaction_config(
    *,
    enabled=True,
    tool_calls=2,
    input_tokens=0,
    current_input_tokens=0,
    output_tokens=0,
    **extra,
):
    config = {
        "toolContextCompactionEnabled": enabled,
        "toolContextCompactionEveryToolCalls": tool_calls,
        "toolContextCompactionInputTokens": input_tokens,
        "toolContextCompactionCurrentInputTokens": current_input_tokens,
        "toolContextCompactionOutputTokens": output_tokens,
    }
    config.update(extra)
    return config


def test_tool_context_compaction_provider_disable_prevents_counting(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config = _compaction_config(enabled=False, tool_calls=1)
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
    ]

    ran = agent._run_tool_context_compaction_gate_if_needed(
        [ToolCallExecution("read_file", "call-1", "alpha raw file content")]
    )

    assert ran is False
    assert agent._tool_context_compaction_window.regular_tool_executions == 0
    assert agent.sent_tools == []


def test_tool_context_compaction_provider_enabled_runs_gate(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config = _compaction_config(tool_calls=1)
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
    ]

    ran = agent._run_tool_context_compaction_gate_if_needed(
        [ToolCallExecution("read_file", "call-1", "alpha raw file content")]
    )

    assert ran is True
    assert agent.sent_tools == []
    assert agent._tool_context_compaction_gate_active is True
    assert agent._tool_context_compaction_window.regular_tool_executions == 1


def test_tool_context_compaction_provider_threshold_delays_gate(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config = _compaction_config(tool_calls=100)
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
    ]

    ran = agent._run_tool_context_compaction_gate_if_needed(
        [ToolCallExecution("read_file", "call-1", "alpha raw file content")]
    )

    assert ran is False
    assert agent.sent_tools == []
    assert agent._tool_context_compaction_window.regular_tool_executions == 1


@pytest.mark.parametrize(
    ("input_limit", "output_limit", "actual_input", "actual_output"),
    [
        (100, 0, 100, 0),
        (0, 25, 0, 25),
    ],
)
def test_tool_context_compaction_actual_token_limit_triggers_gate(
    tmp_path,
    input_limit,
    output_limit,
    actual_input,
    actual_output,
):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyUsageCompactionAgent(memory_path)
    agent.config = _compaction_config(
        tool_calls=0,
        input_tokens=input_limit,
        output_tokens=output_limit,
    )
    agent.actual_input_tokens = actual_input
    agent.actual_output_tokens = actual_output
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
    ]

    ran = agent._run_tool_context_compaction_gate_if_needed(
        [ToolCallExecution("read_file", "call-1", "alpha raw file content")]
    )

    assert ran is True
    assert agent.sent_tools == []
    assert agent._tool_context_compaction_gate_active is True


def test_tool_context_compaction_current_input_limit_uses_latest_request(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyUsageCompactionAgent(memory_path)
    agent.config = _compaction_config(
        tool_calls=0,
        current_input_tokens=50_000,
    )
    agent.actual_input_tokens = 2_000_000
    agent.last_actual_input_tokens = 50_000
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
    ]

    ran = agent._run_tool_context_compaction_gate_if_needed(
        [ToolCallExecution("read_file", "call-1", "alpha raw file content")]
    )

    assert ran is True
    assert agent._tool_context_compaction_gate_active is True


def test_tool_context_compaction_emits_model_window_trigger_evidence(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyUsageCompactionAgent(memory_path)
    agent.config = _compaction_config(
        tool_calls=0,
        modelContextWindowTokens=272_000,
        toolContextCompactionContextPercent=90,
    )
    agent.last_actual_input_tokens = 244_800
    notices = []
    agent._emit_provider_runtime_notice = lambda **payload: notices.append(payload)
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {
            "role": "tool",
            "content": "alpha raw file content",
            "tool_call_id": "call-1",
            "name": "read_file",
        },
    ]

    ran = agent._run_tool_context_compaction_gate_if_needed(
        [ToolCallExecution("read_file", "call-1", "alpha raw file content")]
    )

    assert ran is True
    assert notices[0]["stage"] == "tool_context_compaction_triggered"
    payload = json.loads(notices[0]["message"])
    assert payload["reasons"] == ["current_input_tokens"]
    assert payload["limits"]["current_input_tokens"] == 244_800
    assert payload["limits"]["model_context_window_tokens"] == 272_000


def test_tool_context_compaction_resets_token_baseline_after_tool_completion(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyUsageCompactionAgent(memory_path)
    agent.config = _compaction_config(tool_calls=0, input_tokens=100)
    agent.actual_input_tokens = 100
    agent.compaction_input_tokens = 40
    agent.compaction_output_tokens = 5
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
    ]

    first_ran = agent._run_tool_context_compaction_gate_if_needed(
        [ToolCallExecution("read_file", "call-1", "alpha raw file content")]
    )

    assert first_ran is True
    assert agent.actual_input_tokens == 100
    completion = agent.tools.execute_tool(
        "compact_tool_context",
        {
            "action": "replace",
            "reason": "Replace the inspected tool exchange.",
            "summary": _checkpoint("alpha.py was inspected."),
        },
    )
    assert agent._tool_context_compaction_gate_completed(
        [ToolCallExecution("compact_tool_context", "compact-gate", completion)]
    ) is True
    assert agent._tool_context_compaction_window.input_tokens_baseline == 100
    assert agent._tool_context_compaction_window.output_tokens_baseline == 0

    agent.actual_input_tokens = 199
    agent.messages.extend(
        [
            _tool_call_message("call-2", "read_file"),
            {"role": "tool", "content": "beta raw file content", "tool_call_id": "call-2", "name": "read_file"},
        ]
    )
    second_ran = agent._run_tool_context_compaction_gate_if_needed(
        [ToolCallExecution("read_file", "call-2", "beta raw file content")]
    )

    assert second_ran is False
    assert agent.sent_tools == []

    agent.actual_input_tokens = 200
    agent.messages.extend(
        [
            _tool_call_message("call-3", "read_file"),
            {"role": "tool", "content": "gamma raw file content", "tool_call_id": "call-3", "name": "read_file"},
        ]
    )
    third_ran = agent._run_tool_context_compaction_gate_if_needed(
        [ToolCallExecution("read_file", "call-3", "gamma raw file content")]
    )

    assert third_ran is True
    assert agent._tool_context_compaction_gate_active is True


def test_tool_context_compaction_requires_provider_enabled(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config = {"toolContextCompactionEveryToolCalls": 1}
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
    ]

    try:
        agent._run_tool_context_compaction_gate_if_needed(
            [ToolCallExecution("read_file", "call-1", "alpha raw file content")]
        )
    except ValueError as exc:
        assert "provider.toolContextCompactionEnabled is required" in str(exc)
    else:
        raise AssertionError("missing provider.toolContextCompactionEnabled should fail")


def test_tool_context_compaction_requires_provider_threshold_when_enabled(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config = {"toolContextCompactionEnabled": True}
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
    ]

    try:
        agent._run_tool_context_compaction_gate_if_needed(
            [ToolCallExecution("read_file", "call-1", "alpha raw file content")]
        )
    except ValueError as exc:
        assert "provider.toolContextCompactionEveryToolCalls is required" in str(exc)
    else:
        raise AssertionError("missing provider.toolContextCompactionEveryToolCalls should fail")


@pytest.mark.parametrize(
    "missing_key",
    [
        "toolContextCompactionInputTokens",
        "toolContextCompactionOutputTokens",
    ],
)
def test_tool_context_compaction_requires_all_limit_fields_when_enabled(tmp_path, missing_key):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config = _compaction_config(tool_calls=1)
    agent.config.pop(missing_key)

    with pytest.raises(ValueError, match=missing_key):
        agent._tool_context_compaction_limits()


def test_tool_context_compaction_rejects_boolean_threshold(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config = _compaction_config(tool_calls=True)

    with pytest.raises(ValueError, match="toolContextCompactionEveryToolCalls"):
        agent._tool_context_compaction_limits()


def test_tool_context_compaction_rejects_invalid_prompt_limit(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config = _compaction_config(
        tool_calls=1,
        toolContextCompactionMaxPromptChars="small",
    )

    with pytest.raises(ValueError, match="toolContextCompactionMaxPromptChars"):
        agent._tool_context_compaction_max_prompt_chars()


def test_tool_context_compaction_gate_replaces_eligible_window(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
        _tool_call_message("call-2", "rg_search_text"),
        {"role": "tool", "content": "beta raw search result", "tool_call_id": "call-2", "name": "rg_search_text"},
    ]

    ran = agent._run_tool_context_compaction_gate_if_needed(
        [
            ToolCallExecution("read_file", "call-1", "alpha raw file content"),
            ToolCallExecution("rg_search_text", "call-2", "beta raw search result"),
        ]
    )

    assert ran is True
    assert agent.sent_tools == []
    assert agent._tool_context_compaction_gate_active is True
    assert [item["function"]["name"] for item in agent._tool_context_compaction_active_tools([])] == [
        "compact_tool_context"
    ]
    result = agent.tools.execute_tool(
        "compact_tool_context",
        {
            "action": "replace",
            "reason": "The tool window has been reviewed.",
            "summary": _checkpoint(
                "Inspected alpha.py and beta.py; keep the beta.py finding."
            ),
        },
    )
    assert json.loads(result)["ok"] is True
    assert agent._tool_context_compaction_gate_completed(
        [ToolCallExecution("compact_tool_context", "compact-gate", result)]
    ) is True
    assert len(agent.messages) == 2
    assert agent.messages[0] == {"role": "user", "content": "inspect files"}
    assert agent.messages[1]["role"] == "system"
    assert "[Tool Context Summary]" in agent.messages[1]["content"]
    assert "beta.py finding" in agent.messages[1]["content"]
    assert "compact_tool_context" not in json.dumps(agent.messages, ensure_ascii=False)
    assert "compact_tool_context" not in agent.tools.function_map


def test_tool_context_compaction_replace_keeps_tool_exchange_atomically(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
        _tool_call_message("call-2", "rg_search_text"),
        {"role": "tool", "content": "beta raw search result", "tool_call_id": "call-2", "name": "rg_search_text"},
    ]
    candidates = agent._collect_tool_context_compaction_candidates()
    agent._tool_context_compaction_gate_active = True
    agent._tool_context_compaction_target_messages = agent.messages
    agent._tool_context_compaction_candidate_map = {
        str(item["message_id"]): int(item["index"]) for item in candidates
    }

    result = agent._apply_tool_context_compaction(
        action="replace",
        reason="Keep the first exchange for direct follow-up.",
        summary=_checkpoint("The second exchange was summarized."),
        keep_message_ids=["tc_1"],
        delete_message_ids=[],
        rewrites=[],
    )

    assert result["ok"] is True
    assert result["removed_count"] == 2
    assert [item["role"] for item in agent.messages] == ["user", "assistant", "tool", "system"]
    assert agent.messages[1]["tool_calls"][0]["id"] == "call-1"
    assert agent.messages[2]["tool_call_id"] == "call-1"
    assert "call-2" not in json.dumps(agent.messages, ensure_ascii=False)


def test_tool_context_compaction_gate_prompt_does_not_duplicate_tool_context(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.messages = [
        {"role": "user", "content": "old request"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "current request: inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
        _tool_call_message("call-2", "rg_search_text"),
        {"role": "tool", "content": "beta raw search result", "tool_call_id": "call-2", "name": "rg_search_text"},
    ]

    ran = agent._run_tool_context_compaction_gate_if_needed(
        [
            ToolCallExecution("read_file", "call-1", "alpha raw file content"),
            ToolCallExecution("rg_search_text", "call-2", "beta raw search result"),
        ]
    )

    assert ran is True
    prompt = agent.messages[-1]["content"]
    assert "tool-call history already present in the conversation" in prompt
    assert "current request: inspect files" not in prompt
    assert "alpha raw file content" not in prompt
    assert "beta raw search result" not in prompt
    assert len(prompt) < 3000


def test_responses_compaction_messages_use_developer_role(tmp_path):
    from src.providers.openai_mapping import OpenAIResponsesMapping

    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config["responsesApi"] = True
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "raw content", "tool_call_id": "call-1", "name": "read_file"},
        _tool_call_message("call-2", "rg_search_text"),
        {"role": "tool", "content": "search result", "tool_call_id": "call-2", "name": "rg_search_text"},
    ]

    assert agent._run_tool_context_compaction_gate_if_needed(
        [
            ToolCallExecution("read_file", "call-1", "raw content"),
            ToolCallExecution("rg_search_text", "call-2", "search result"),
        ]
    ) is True
    assert agent.messages[-1]["role"] == "developer"
    assert not any(message.get("role") == "system" for message in agent.messages)
    request_input = OpenAIResponsesMapping(agent)._build_responses_input(agent.messages)
    assert request_input[-1]["role"] == "developer"
    assert not any(item.get("role") == "system" for item in request_input)

    agent._retry_tool_context_compaction_gate("retry requested")
    retry_messages = [
        message
        for message in agent.messages
        if str(message.get("content") or "").startswith("[Tool Context Compaction Retry]")
    ]
    assert retry_messages[-1]["role"] == "developer"

    result = agent.tools.execute_tool(
        "compact_tool_context",
        {
            "action": "replace",
            "reason": "The tool window has been reviewed.",
            "summary": _checkpoint("The relevant file findings are preserved."),
        },
    )
    assert json.loads(result)["ok"] is True
    summaries = [
        message
        for message in agent.messages
        if str(message.get("content") or "").startswith("[Tool Context Summary]")
    ]
    normalized_summaries = agent._normalize_provider_messages(summaries)
    assert len(normalized_summaries) == 1
    assert normalized_summaries[0]["role"] == "developer"
    assert normalized_summaries[0]["content"].startswith(
        "[Tool Context Summary]\nReason: The tool window has been reviewed.\n"
    )
    assert '"completed_facts": [' in normalized_summaries[0]["content"]
    assert "The relevant file findings are preserved." in normalized_summaries[0]["content"]
    assert not any(message.get("role") == "system" for message in agent.messages)


def test_responses_blocked_tool_warning_and_compaction_gate_never_replay_system(tmp_path):
    from src.providers.openai_mapping import OpenAIResponsesMapping
    from src.providers.openai_responses_runtime import OpenAIResponsesRuntime

    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config = _compaction_config(
        tool_calls=1,
        responsesApi=True,
        toolResultSubmissionMaxChars=50000,
    )
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-blocked", "execute_console_command"),
    ]
    blocked = ToolCallExecution(
        "execute_console_command",
        "call-blocked",
        json.dumps(
            {
                "status": "blocked",
                "retryable": False,
                "reason": "command policy blocked the request",
            }
        ),
        status="blocked",
    )

    followup = OpenAIResponsesRuntime(agent)._build_responses_followup_items([blocked])

    assert len(followup) == 1
    warnings = [
        message
        for message in agent.messages
        if "non-retryable result" in str(message.get("content") or "")
    ]
    assert warnings[-1]["role"] == "developer"
    assert agent._run_tool_context_compaction_gate_if_needed([blocked]) is True

    replay_input = OpenAIResponsesMapping(agent)._build_responses_input(agent.messages)
    assert any(item.get("role") == "developer" for item in replay_input)
    assert not any(item.get("role") == "system" for item in replay_input)


def test_tool_context_compaction_patch_deletes_and_rewrites_only_eligible_messages(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "raw file content", "tool_call_id": "call-1", "name": "read_file"},
    ]
    candidates = agent._collect_tool_context_compaction_candidates()
    agent._tool_context_compaction_gate_active = True
    agent._tool_context_compaction_target_messages = agent.messages
    agent._tool_context_compaction_candidate_map = {
        str(item["message_id"]): int(item["index"]) for item in candidates
    }

    result = agent._apply_tool_context_compaction(
        action="patch",
        reason="Keep the call but shrink the result.",
        summary=_checkpoint("read_file returned the needed function body."),
        keep_message_ids=[],
        delete_message_ids=["tc_1"],
        rewrites=[{"message_id": "tc_2", "content": "read_file summary"}],
    )

    assert result["ok"] is True
    assert result["removed_count"] == 2
    assert result["rewritten_count"] == 0
    assert [item["role"] for item in agent.messages] == ["user", "system"]
    assert "call-1" not in json.dumps(agent.messages, ensure_ascii=False)


def test_tool_context_compaction_rejects_summary_without_reducing_context(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "raw file content", "tool_call_id": "call-1", "name": "read_file"},
    ]
    original_messages = copy.deepcopy(agent.messages)
    candidates = agent._collect_tool_context_compaction_candidates()
    agent._tool_context_compaction_gate_active = True
    agent._tool_context_compaction_target_messages = agent.messages
    agent._tool_context_compaction_candidate_map = {
        str(item["message_id"]): int(item["index"]) for item in candidates
    }

    with pytest.raises(ValueError, match="must delete or rewrite"):
        agent._apply_tool_context_compaction(
            action="patch",
            reason="Only add a summary.",
            summary=_checkpoint("This does not actually compact anything."),
            keep_message_ids=[],
            delete_message_ids=[],
            rewrites=[],
        )

    assert agent.messages == original_messages


def test_tool_context_compaction_gate_allows_a_substantive_final_response(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
        _tool_call_message("call-2", "rg_search_text"),
        {"role": "tool", "content": "beta raw search result", "tool_call_id": "call-2", "name": "rg_search_text"},
    ]

    ran = agent._run_tool_context_compaction_gate_if_needed(
        [
            ToolCallExecution("read_file", "call-1", "alpha raw file content"),
            ToolCallExecution("rg_search_text", "call-2", "beta raw search result"),
        ]
    )

    assert ran is True
    assert [item["function"]["name"] for item in agent._tool_context_compaction_active_tools([{"type": "web_search"}])] == [
        "compact_tool_context"
    ]
    assert agent._finish_tool_context_compaction_gate_with_response("   ") is False
    assert agent._tool_context_compaction_gate_active is True
    assert agent._finish_tool_context_compaction_gate_with_response("The task is complete.") is True
    assert agent._tool_context_compaction_gate_active is False
    assert "compact_tool_context" not in agent.tools.function_map
    assert "Tool calls have accumulated" not in json.dumps(agent.messages, ensure_ascii=False)
    assert "alpha raw file content" in json.dumps(agent.messages, ensure_ascii=False)


def test_tool_context_compaction_gate_restores_existing_function_map_entry(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    sentinel = object()
    agent.tools.function_map["compact_tool_context"] = sentinel
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
        _tool_call_message("call-2", "rg_search_text"),
        {"role": "tool", "content": "beta raw search result", "tool_call_id": "call-2", "name": "rg_search_text"},
    ]

    ran = agent._run_tool_context_compaction_gate_if_needed(
        [
            ToolCallExecution("read_file", "call-1", "alpha raw file content"),
            ToolCallExecution("rg_search_text", "call-2", "beta raw search result"),
        ]
    )

    assert ran is True
    assert agent.tools.function_map["compact_tool_context"] is not sentinel
    result = agent.tools.execute_tool(
        "compact_tool_context",
        {
            "action": "replace",
            "reason": "Replace the inspected tool exchanges.",
            "summary": _checkpoint(
                "The relevant file findings are preserved for continuation."
            ),
        },
    )
    assert agent._tool_context_compaction_gate_completed(
        [ToolCallExecution("compact_tool_context", "compact-gate", result)]
    ) is True
    assert agent.tools.function_map["compact_tool_context"] is sentinel


def test_failed_compaction_execution_keeps_gate_active(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config = _compaction_config(tool_calls=1)
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "raw content", "tool_call_id": "call-1", "name": "read_file"},
    ]
    assert agent._run_tool_context_compaction_gate_if_needed(
        [ToolCallExecution("read_file", "call-1", "raw content")]
    ) is True

    completed = agent._tool_context_compaction_gate_completed(
        [
            ToolCallExecution(
                "compact_tool_context",
                "compact-gate",
                '{"status":"exception","error":"invalid arguments"}',
                status="exception",
                error="invalid arguments",
            )
        ]
    )

    assert completed is False
    assert agent._tool_context_compaction_gate_active is True
    assert [item["function"]["name"] for item in agent._tool_context_compaction_active_tools([])] == [
        "compact_tool_context"
    ]
