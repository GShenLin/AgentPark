import json
from pathlib import Path

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


def test_deepseek_chat_payload_normalizes_restored_developer_instruction_to_system():
    agent = _build_deepseek_agent()
    agent.messages = [
        {"role": "developer", "content": "Instruction restored from a Responses provider."},
        {"role": "user", "content": "hello"},
    ]

    payload = _capture_payload(agent)

    assert payload["messages"] == [
        {"role": "system", "content": "Instruction restored from a Responses provider."},
        {"role": "user", "content": "hello"},
    ]
    assert all(message["role"] != "developer" for message in payload["messages"])


def test_deepseek_stream_does_not_retry_http_402(monkeypatch):
    from src.providers.deepseek_chat_runtime import DeepSeekChatRuntime
    from src.providers.openai_transport_errors import OpenAIHttpError

    runtime = DeepSeekChatRuntime(_build_deepseek_agent())
    runtime.config = {"maxRetries": 3, "retryDelaySec": 0}
    calls = {"count": 0}

    def fail_once(**_kwargs):
        calls["count"] += 1
        raise OpenAIHttpError(
            402,
            '{"error":{"message":"Insufficient Balance"}}',
        )

    monkeypatch.setattr(runtime, "_stream_chat_completions_once", fail_once)

    with pytest.raises(RuntimeError, match="HTTP 402"):
        runtime._stream_chat_completions_with_retry(
            endpoint="chat/completions",
            url="https://api.deepseek.test/chat/completions",
            headers={},
            payload_json="{}",
            stream_handler=None,
        )

    assert calls["count"] == 1


def test_tavern_provider_uses_official_deepseek_non_thinking_contract():
    config_path = Path(__file__).resolve().parents[1] / "config" / "modelProvider.json"
    providers = json.loads(config_path.read_text(encoding="utf-8"))["providers"]
    provider = providers["tavern_deepseek_v31"]

    assert provider["type"] == "deepseek"
    assert provider["model"] == "deepseek-v4-pro"


def test_deepseek_send_uses_responses_endpoint_when_enabled():
    agent = _build_deepseek_agent()
    agent.config["responsesApi"] = True
    agent.config["reasoningEffort"] = "high"
    agent.config["responsesReplayReasoningItems"] = False
    requests = []

    def fake_post(**kwargs):
        requests.append(kwargs)
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "responses ok"}],
                }
            ]
        }

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post
    agent._stream_chat_completions_with_retry = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("responsesApi=true must not use chat/completions")
    )

    result = agent.Send(
        web_search="disabled",
        thinking="enabled",
        reasoning_effort="high",
        reasoning_summary="disabled",
        stream=False,
    )

    assert result == "responses ok"
    assert requests[0]["endpoint"] == "responses"
    assert requests[0]["url"] == "https://api.deepseek.test/responses"
    payload = json.loads(requests[0]["payload_json"])
    assert payload["model"] == "deepseek-test"
    assert "input" in payload
    assert "messages" not in payload
    assert payload["reasoning"] == {"effort": "high"}


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


def test_deepseek_serializes_structured_tool_result_content_as_json_text():
    agent = _build_deepseek_agent()
    agent.tools.function_map["market_data"] = lambda: {
        "status": "ok",
        "data": {"symbol": "000300.SH", "close": [3988.42]},
    }
    responses = iter(
        [
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_market_data",
                                    "type": "function",
                                    "function": {"name": "market_data", "arguments": "{}"},
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
    tool_message = requests[1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert isinstance(tool_message["content"], str)
    assert json.loads(tool_message["content"]) == {
        "status": "ok",
        "data": {"symbol": "000300.SH", "close": [3988.42]},
    }


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


def test_bundled_deepseek_v4_providers_use_deepseek_runtime():
    provider_document = json.loads(
        (Path(__file__).parents[1] / "config" / "modelProvider.json").read_text(encoding="utf-8")
    )

    assert provider_document["providers"]["deepseek_v4_flash"]["type"] == "deepseek"
    assert provider_document["providers"]["deepseek_v4_pro"]["type"] == "deepseek"


def test_model_provider_settings_can_select_deepseek_type():
    component = (
        Path(__file__).parents[1]
        / "webui"
        / "src"
        / "components"
        / "settings"
        / "ProviderAuthFields.vue"
    ).read_text(encoding="utf-8")

    assert '<option value="deepseek">deepseek</option>' in component
