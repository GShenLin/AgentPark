import json
import os

import pytest


pytestmark = pytest.mark.skipif(
    os.environ.get("AGENTPARK_RUN_KRILL_RESPONSES_LIVE") != "1",
    reason="live Krill Responses multi-tool continuation test is opt-in",
)


def test_krill_responses_explicit_context_preserves_five_tool_call_task():
    from src.providers.openai_agent import OpenAIAgent
    from src.tool.base_tool import BaseTool

    agent = OpenAIAgent(provider_id="krill_gpt55", internal_memory_enabled=False)
    agent.config = dict(agent.config)
    agent.config["responsesReplayReasoningItems"] = False
    agent.config["toolContextCompactionEnabled"] = False
    agent.config["reasoningEffort"] = "low"
    agent.tools = BaseTool(agent)
    observed_calls = []
    payloads = []

    declaration = {
        "type": "function",
        "function": {
            "name": "record_probe_call",
            "description": (
                "Record one required continuation probe call. Call this exactly once per model turn "
                "with the next index until all five calls are complete."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "index": {
                        "type": "integer",
                        "description": "The 1-based probe call index. Use 1, then 2, then 3, then 4, then 5.",
                    }
                },
                "required": ["index"],
                "additionalProperties": False,
            },
        },
    }

    def record_probe_call(index=None):
        observed_calls.append(index)
        return json.dumps(
            {
                "status": "continue" if len(observed_calls) < 5 else "complete",
                "received_index": index,
                "observed_count": len(observed_calls),
                "required_count": 5,
                "next_index": len(observed_calls) + 1 if len(observed_calls) < 5 else None,
                "instruction": (
                    "If status is continue, call record_probe_call again and do not send a final answer. "
                    "If status is complete, answer KRILL_TOOL_LOOP_DONE: 1,2,3,4,5."
                ),
            },
            ensure_ascii=False,
        )

    agent.tools.register_external_tool(declaration, record_probe_call)
    real_post = agent._post_json_with_retry

    def recording_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return real_post(**kwargs)

    agent._post_json_with_retry = recording_post

    prompt = (
        "Call the tool five times. You are testing tool continuation. You must call record_probe_call exactly "
        "five times, one at a time, with index 1 then 2 then 3 then 4 then 5. Never answer while "
        "the latest tool result has status continue. After status complete, answer exactly: "
        "KRILL_TOOL_LOOP_DONE: 1,2,3,4,5"
    )
    result = agent._send_via_responses(
        messages=[{"role": "user", "content": prompt}],
        active_tools=agent.tools.tool_declarations,
        run_tools=True,
        reasoning_effort="low",
    )

    assert observed_calls == [1, 2, 3, 4, 5]
    assert "KRILL_TOOL_LOOP_DONE: 1,2,3,4,5" in result
    assert len(payloads) >= 6
    for index, payload in enumerate(payloads[1:], start=1):
        assert "previous_response_id" not in payload
        input_text = json.dumps(payload.get("input"), ensure_ascii=False)
        assert "Call the tool five times" in input_text
        for completed in range(1, min(index, 5) + 1):
            assert f"call-{completed}" in input_text or f'\\"received_index\\": {completed}' in input_text
