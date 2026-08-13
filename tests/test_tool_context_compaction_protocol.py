import json

from src.providers.openai_agent import OpenAIAgent
from src.tool.base_tool import BaseTool
from src.tool.tool_call_protocol import ToolCallEnvelope


def _compaction_gate_agent() -> OpenAIAgent:
    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {}
    agent.provider_name = "openai"
    agent.tools = BaseTool(agent)
    agent._tool_context_compaction_gate_active = True
    agent._reset_tool_call_loop_guard()
    return agent


def test_compaction_gate_rejection_explains_the_only_available_tool():
    agent = _compaction_gate_agent()
    call = ToolCallEnvelope(
        name="execute_console_command",
        call_id="shell-1",
        arguments={"command": "echo blocked"},
        arguments_json='{"command":"echo blocked"}',
        provider="unit",
    )

    results = agent._execute_tool_call_envelopes_parallel([call])

    assert len(results) == 1
    assert results[0].status == "rejected"
    payload = json.loads(results[0].cleaned_result)
    assert "compact_tool_context is the only function tool currently available" in payload["error"]
    assert "ordinary function tools are restored after compaction succeeds" in payload["error"]


def test_compaction_gate_distinguishes_a_duplicate_compaction_call():
    agent = _compaction_gate_agent()
    agent.tools.function_map["compact_tool_context"] = lambda **_kwargs: '{"ok":true}'
    calls = [
        ToolCallEnvelope(
            name="compact_tool_context",
            call_id=f"compact-{index}",
            arguments={},
            arguments_json="{}",
            provider="unit",
        )
        for index in (1, 2)
    ]

    results = agent._execute_tool_call_envelopes_parallel(calls)

    assert results[0].status == "completed"
    assert results[1].status == "rejected"
    payload = json.loads(results[1].cleaned_result)
    assert "Only one compact_tool_context call is allowed" in payload["error"]
    assert "Wait for the admitted compact_tool_context result" in payload["error"]
