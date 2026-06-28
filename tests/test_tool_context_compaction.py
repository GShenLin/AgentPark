import json

import pytest

from src.base_agent import BaseAgent
from src.tool.tool_call_protocol import ToolCallExecution
from src.tool_context_compaction_gate import TOOL_CONTEXT_COMPACTION_REFUSED_ERROR
from src.tool_context_compaction_gate import TOOL_CONTEXT_COMPACTION_REQUIRED_ERROR


class DummyCompactionAgent(BaseAgent):
    def __init__(self, memory_path):
        super().__init__("dummy", memory_file_path=str(memory_path), internal_memory_enabled=False)
        self.tool_context_compaction_gate_enabled = True
        self.sent_tools = []
        self.last_gate_messages = []
        self.config = {
            "toolContextCompactionEnabled": True,
            "toolContextCompactionEveryToolCalls": 2,
        }

    def Send(self, tools=None, run_tools=True, mode="chat", stream=False):
        self.last_gate_messages = list(self.messages)
        self.sent_tools.append(tools)
        result = self.tools.execute_tool(
            "compact_tool_context",
            {
                "action": "replace",
                "reason": "The tool window has been reviewed.",
                "summary": "Inspected alpha.py and beta.py. Keep the beta.py finding for the next step.",
            },
        )
        self.Message("tool", result, persist=False, tool_call_id="compact-gate", name="compact_tool_context")
        return result


class DummyIgnoredCompactionAgent(DummyCompactionAgent):
    def Send(self, tools=None, run_tools=True, mode="chat", stream=False):
        self.last_gate_messages = list(self.messages)
        self.sent_tools.append(tools)
        return "ordinary tool call continued"


class DummyRetryCompactionAgent(DummyCompactionAgent):
    def __init__(self, memory_path):
        super().__init__(memory_path)
        self.gate_attempts = 0

    def Send(self, tools=None, run_tools=True, mode="chat", stream=False):
        self.gate_attempts += 1
        self.last_gate_messages = list(self.messages)
        if self.gate_attempts == 1:
            self.sent_tools.append(tools)
            return "ordinary tool call continued"
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


def test_tool_context_compaction_provider_disable_prevents_counting(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config = {
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
    ]

    ran = agent._run_tool_context_compaction_gate_if_needed(
        [ToolCallExecution("read_file", "call-1", "alpha raw file content")]
    )

    assert ran is False
    assert agent._tool_context_compaction_since_last == 0
    assert agent.sent_tools == []


def test_tool_context_compaction_provider_enabled_runs_gate(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config = {
        "toolContextCompactionEnabled": True,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
    ]

    ran = agent._run_tool_context_compaction_gate_if_needed(
        [ToolCallExecution("read_file", "call-1", "alpha raw file content")]
    )

    assert ran is True
    assert agent.sent_tools
    assert agent._tool_context_compaction_since_last == 0


def test_tool_context_compaction_provider_threshold_delays_gate(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config = {
        "toolContextCompactionEnabled": True,
        "toolContextCompactionEveryToolCalls": 100,
    }
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
    assert agent._tool_context_compaction_since_last == 1


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


def test_tool_context_compaction_rejects_boolean_threshold(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config = {
        "toolContextCompactionEnabled": True,
        "toolContextCompactionEveryToolCalls": True,
    }

    with pytest.raises(ValueError, match="toolContextCompactionEveryToolCalls"):
        agent._tool_context_compaction_threshold()


def test_tool_context_compaction_rejects_invalid_prompt_limit(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyCompactionAgent(memory_path)
    agent.config = {
        "toolContextCompactionEnabled": True,
        "toolContextCompactionEveryToolCalls": 1,
        "toolContextCompactionMaxPromptChars": "small",
    }

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
    assert agent.sent_tools
    assert [item["function"]["name"] for item in agent.sent_tools[0]] == ["compact_tool_context"]
    assert len(agent.messages) == 2
    assert agent.messages[0] == {"role": "user", "content": "inspect files"}
    assert agent.messages[1]["role"] == "system"
    assert "[Tool Context Summary]" in agent.messages[1]["content"]
    assert "beta.py finding" in agent.messages[1]["content"]
    assert "compact_tool_context" not in json.dumps(agent.messages, ensure_ascii=False)
    assert "compact_tool_context" not in agent.tools.function_map


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
        summary="read_file returned the needed function body.",
        keep_message_ids=[],
        delete_message_ids=["tc_1"],
        rewrites=[{"message_id": "tc_2", "content": "read_file summary"}],
    )

    assert result["ok"] is True
    assert result["removed_count"] == 1
    assert result["rewritten_count"] == 1
    assert [item["role"] for item in agent.messages] == ["user", "system", "tool"]
    assert agent.messages[2]["content"] == "read_file summary"


def test_tool_context_compaction_gate_retries_with_error_when_compaction_tool_not_called(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyRetryCompactionAgent(memory_path)
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
    assert agent.gate_attempts == 2
    assert len(agent.sent_tools) == 2
    assert agent.sent_tools[0] == agent.sent_tools[1]
    assert any(
        item.get("content") == TOOL_CONTEXT_COMPACTION_REQUIRED_ERROR
        for item in agent.last_gate_messages
    )


def test_tool_context_compaction_gate_errors_when_compaction_tool_not_called(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyIgnoredCompactionAgent(memory_path)
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
        _tool_call_message("call-2", "rg_search_text"),
        {"role": "tool", "content": "beta raw search result", "tool_call_id": "call-2", "name": "rg_search_text"},
    ]
    original_messages = list(agent.messages)

    with pytest.raises(RuntimeError, match=TOOL_CONTEXT_COMPACTION_REFUSED_ERROR):
        agent._run_tool_context_compaction_gate_if_needed(
            [
                ToolCallExecution("read_file", "call-1", "alpha raw file content"),
                ToolCallExecution("rg_search_text", "call-2", "beta raw search result"),
            ]
        )

    assert len(agent.sent_tools) == 2
    assert agent.messages == original_messages
    assert agent._tool_context_compaction_changed_last_run() is False
    assert agent._tool_context_compaction_since_last == 0
    assert "compact_tool_context" not in agent.tools.function_map
    assert any(
        item.get("content") == TOOL_CONTEXT_COMPACTION_REQUIRED_ERROR
        for item in agent.last_gate_messages
    )


def test_tool_context_compaction_gate_restores_existing_function_map_entry(tmp_path):
    memory_path = tmp_path / "agent.md"
    memory_path.write_text("", encoding="utf-8")
    agent = DummyIgnoredCompactionAgent(memory_path)
    sentinel = object()
    agent.tools.function_map["compact_tool_context"] = sentinel
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        _tool_call_message("call-1", "read_file"),
        {"role": "tool", "content": "alpha raw file content", "tool_call_id": "call-1", "name": "read_file"},
        _tool_call_message("call-2", "rg_search_text"),
        {"role": "tool", "content": "beta raw search result", "tool_call_id": "call-2", "name": "rg_search_text"},
    ]

    with pytest.raises(RuntimeError, match=TOOL_CONTEXT_COMPACTION_REFUSED_ERROR):
        agent._run_tool_context_compaction_gate_if_needed(
            [
                ToolCallExecution("read_file", "call-1", "alpha raw file content"),
                ToolCallExecution("rg_search_text", "call-2", "beta raw search result"),
            ]
        )

    assert agent.tools.function_map["compact_tool_context"] is sentinel
