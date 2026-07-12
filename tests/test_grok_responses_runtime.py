import copy

import pytest

from src.providers.grok_agent import GrokAgent


def _agent(config=None):
    agent = GrokAgent.__new__(GrokAgent)
    agent.config = {
        "model": "grok-4.5",
        "responsesReplayReasoningItems": False,
        **(config or {}),
    }
    agent.provider_name = "grok-test"
    agent._service_targets_cache = None
    return agent


def test_grok_responses_payload_uses_grok_reasoning_contract():
    agent = _agent({"promptCacheKey": "conversation-1"})

    payload = agent._build_responses_payload(
        current_input=[],
        tools_payload=[{"type": "web_search"}],
        use_stream=False,
        provider_options={"reasoning_effort": "high", "reasoning_summary": "detailed"},
    )

    assert payload["reasoning"] == {"effort": "high"}
    assert payload["include"] == ["web_search_call.action.sources"]
    assert payload["prompt_cache_key"] == "conversation-1"


@pytest.mark.parametrize("effort", ["none", "xhigh"])
def test_grok_45_rejects_unsupported_reasoning_effort(effort):
    agent = _agent()

    with pytest.raises(ValueError, match="Grok 4.5 reasoning_effort"):
        agent._build_responses_payload(
            current_input=[],
            tools_payload=[],
            use_stream=False,
            provider_options={"reasoning_effort": effort},
        )


def test_grok_responses_mapping_preserves_xai_hosted_tools():
    agent = _agent()
    tools = [
        {"type": "x_search", "allowed_x_handles": ["xai"]},
        {"type": "code_interpreter"},
        {"type": "file_search", "vector_store_ids": ["collection-1"]},
    ]

    assert agent._build_responses_tools(tools) == tools


def test_grok_web_search_uses_xai_filters():
    agent = _agent(
        {
            "webSearchAllowedDomains": ["example.com"],
            "webSearchEnableImageUnderstanding": True,
        }
    )

    assert agent._build_web_search_tool() == {
        "type": "web_search",
        "filters": {"allowed_domains": ["example.com"]},
        "enable_image_understanding": True,
    }


def test_grok_http_responses_continuation_uses_previous_response_id():
    agent = _agent()
    first_input = [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "one"}]}]
    response_output = [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "first"}],
        }
    ]
    first_payload = agent._build_responses_payload(
        current_input=first_input,
        tools_payload=[],
        use_stream=False,
        provider_options={"reasoning_effort": "high"},
    )
    agent._grok_previous_logical_responses_payload = copy.deepcopy(first_payload)
    agent._grok_previous_responses_result = {"id": "resp_1", "output": response_output}
    second_input = [
        *first_input,
        *response_output,
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "two"}]},
    ]

    second_payload = agent._build_responses_payload(
        current_input=second_input,
        tools_payload=[],
        use_stream=False,
        provider_options={"reasoning_effort": "high"},
    )

    assert second_payload["previous_response_id"] == "resp_1"
    assert second_payload["input"] == [second_input[-1]]


def test_grok_does_not_apply_openai_fc_call_id_validation():
    _agent()._validate_responses_followup_call_id("fc_xai_owned")


def test_grok_agent_rejects_reasoning_summary_before_send():
    agent = _agent()

    with pytest.raises(ValueError, match="does not support reasoning_summary"):
        agent.Send(reasoning_summary="concise")

    with pytest.raises(ValueError, match="does not support reasoning_summary"):
        agent.Send(None, True, "chat", None, None, "high", "concise")
