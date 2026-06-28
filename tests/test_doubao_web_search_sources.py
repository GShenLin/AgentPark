import json
import pytest


def _build_agent():
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://example.com/v1",
        "model": "doubao-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
    }
    agent.provider_name = "doubao"
    agent.Message = lambda *_args, **_kwargs: None
    return agent


def test_send_via_responses_keeps_web_search_fields_and_no_auto_strip():
    agent = _build_agent()
    payloads = []

    def _fake_post_json_with_retry(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        payloads.append(payload)
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "ok"}],
                }
            ]
        }

    agent._post_json_with_retry = _fake_post_json_with_retry
    agent._stream_responses_with_retry = _fake_post_json_with_retry

    result = agent._send_via_responses(
        messages=[{"role": "user", "content": "today llm news"}],
        active_tools=[
            {
                "type": "web_search",
                "max_keyword": 5,
                "limit": 10,
                "sources": ["toutiao"],
                "user_location": {"country": "CN", "region": "Beijing", "city": "Beijing"},
            }
        ],
        run_tools=False,
        thinking_mode="enabled",
        web_search_mode="enabled",
    )

    assert result == "ok"
    assert len(payloads) == 1
    sent_tool = payloads[0]["tools"][0]
    assert sent_tool.get("type") == "web_search"
    assert sent_tool.get("sources") == ["toutiao"]
    assert isinstance(sent_tool.get("user_location"), dict)
    assert sent_tool["user_location"] == {"country": "CN", "region": "Beijing", "city": "Beijing"}


def test_web_search_requires_explicit_responses_api_support():
    from src.tool.base_tool import BaseTool
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://api.deepseek.com",
        "model": "deepseek-test",
        "maxRetries": 0,
        "retryDelaySec": 0,
        "type": "doubao",
    }
    agent.provider_name = "deepseek_test"
    agent.system_prompt = None
    agent.messages = [{"role": "user", "content": "search"}]
    agent.tools = BaseTool(agent)
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)

    with pytest.raises(ValueError, match="responsesApi=true"):
        agent.Send(run_tools=False, web_search="enabled")


def test_doubao_responses_empty_output_feeds_back_error_before_returning_final_message():
    agent = _build_agent()
    payloads = []

    def _fake_post_json_with_retry(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        payloads.append(payload)
        if len(payloads) == 1:
            return {"output": []}
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "ok after feedback"}],
                }
            ]
        }

    agent._post_json_with_retry = _fake_post_json_with_retry
    agent._stream_responses_with_retry = _fake_post_json_with_retry

    result = agent._send_via_responses(
        messages=[{"role": "user", "content": "say something"}],
        active_tools=[],
        run_tools=False,
        thinking_mode="enabled",
        web_search_mode="disabled",
    )

    assert result == "ok after feedback"
    assert len(payloads) == 2
    feedback_text = payloads[1]["input"][-1]["content"][0]["text"]
    assert feedback_text.startswith("Error: EmptyMessage\n")
    feedback_payload = json.loads(feedback_text.split("\n", 1)[1])
    assert feedback_payload["error"] == "EmptyMessage"
    assert "input" in feedback_payload
    assert "item" in feedback_payload


def test_doubao_responses_resets_stream_text_between_tool_turns():
    from src.tool.tool_call_protocol import ToolCallExecution

    agent = _build_agent()
    payloads = []

    def _fake_stream_responses_with_retry(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        handler = kwargs.get("stream_handler")
        if len(payloads) == 1:
            if callable(handler):
                handler("tool intro", "tool intro")
            return {
                "id": "resp-tool",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "rg_list_files",
                        "arguments": "{}",
                    }
                ],
            }
        if len(payloads) == 2:
            return {"id": "resp-empty", "output": []}
        return {
            "id": "resp-final",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "recovered after empty response"}],
                }
            ],
        }

    agent._stream_responses_with_retry = _fake_stream_responses_with_retry
    agent._execute_tool_call_envelopes_parallel = lambda _calls: [
        ToolCallExecution(
            func_name="rg_list_files",
            call_id="call-1",
            cleaned_result='{"status":"success","files":["README.md"]}',
            image_data=None,
        )
    ]

    result = agent._send_via_responses(
        messages=[{"role": "user", "content": "run rg"}],
        active_tools=[],
        run_tools=True,
        thinking_mode="enabled",
        web_search_mode="disabled",
        stream_handler=lambda _delta, _full: None,
    )

    assert result == "recovered after empty response"
    assert len(payloads) == 3
    feedback_text = payloads[2]["input"][-1]["content"][0]["text"]
    assert feedback_text.startswith("Error: EmptyMessage\n")
