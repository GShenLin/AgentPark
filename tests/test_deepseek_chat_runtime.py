import json

import pytest


def _build_deepseek_agent():
    from src.providers.deepseek_agent import DeepSeekAgent
    from src.tool.base_tool import BaseTool

    agent = DeepSeekAgent.__new__(DeepSeekAgent)
    agent.config = {
        "type": "deepseek",
        "apiKey": "test-key",
        "baseUrl": "https://api.deepseek.test",
        "model": "deepseek-test",
        "responsesApi": False,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
        "features": {
            "thinking": {"supported": True, "values": ["enabled", "disabled"]},
        },
    }
    agent.provider_name = "deepseek-test"
    agent.system_prompt = None
    agent.messages = [{"role": "user", "content": "hello"}]
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.tool_declarations = []
    agent._service_targets_cache = None
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    return agent


def _capture_payload(agent, **send_options):
    requests = []

    def fake_post(**kwargs):
        requests.append(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    agent._curl_post_json_once = fake_post
    assert agent.Send(web_search="disabled", stream=False, **send_options) == "ok"
    return json.loads(requests[0]["payload_json"])


def test_deepseek_explicitly_disables_thinking_and_omits_reasoning_effort():
    payload = _capture_payload(
        _build_deepseek_agent(),
        thinking="disabled",
        reasoning_effort="high",
    )

    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload


@pytest.mark.parametrize("effort", ["high", "max"])
def test_deepseek_sends_supported_reasoning_effort_when_thinking_is_enabled(effort):
    payload = _capture_payload(
        _build_deepseek_agent(),
        thinking="enabled",
        reasoning_effort=effort,
    )

    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == effort


def test_deepseek_rejects_auto_thinking():
    with pytest.raises(ValueError, match="DeepSeek thinking"):
        _capture_payload(_build_deepseek_agent(), thinking="auto")


def test_deepseek_rejects_unsupported_reasoning_effort_when_thinking_is_enabled():
    with pytest.raises(ValueError, match="DeepSeek reasoning_effort"):
        _capture_payload(
            _build_deepseek_agent(),
            thinking="enabled",
            reasoning_effort="xhigh",
        )


def test_deepseek_replays_reasoning_content_after_tool_call():
    agent = _build_deepseek_agent()
    agent.tools.function_map["echo_tool"] = lambda message=None: f"echo:{message}"
    responses = iter(
        [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "reasoning_content": "I should use the echo tool.",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "echo_tool", "arguments": '{"message":"hello"}'},
                                }
                            ],
                        }
                    }
                ]
            },
            {"choices": [{"message": {"role": "assistant", "content": "done"}}]},
        ]
    )
    requests = []

    def fake_post(**kwargs):
        requests.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._curl_post_json_once = fake_post

    assert agent.Send(thinking="enabled", reasoning_effort="high", stream=False) == "done"
    assistant_tool_call = requests[1]["messages"][1]
    assert assistant_tool_call["reasoning_content"] == "I should use the echo tool."
    assert assistant_tool_call["tool_calls"][0]["function"]["name"] == "echo_tool"


def test_deepseek_stream_assembles_reasoning_content_for_tool_call_replay():
    agent = _build_deepseek_agent()
    agent.tools.function_map["echo_tool"] = lambda message=None: f"echo:{message}"
    requests = []
    streams = iter(
        [
            [
                '{"choices":[{"delta":{"reasoning_content":"Use echo.","tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"echo_tool","arguments":"{\\"message\\":\\"hello\\"}"}}]}}]}',
                "[DONE]",
            ],
            [
                '{"choices":[{"delta":{"content":"done"}}]}',
                "[DONE]",
            ],
        ]
    )

    def fake_stream(**kwargs):
        requests.append(json.loads(kwargs["payload_json"]))
        return iter(next(streams))

    agent._curl_post_sse_data_lines = fake_stream

    assert agent.Send(thinking="enabled", reasoning_effort="high", stream=True) == "done"
    assert requests[1]["messages"][1]["reasoning_content"] == "Use echo."
