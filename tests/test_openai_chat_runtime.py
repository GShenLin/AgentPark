import json


def _build_openai_chat_agent():
    from src.providers.openai_agent import OpenAIAgent
    from src.tool.base_tool import BaseTool

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://chat.example/v1",
        "model": "chat-model",
        "responsesApi": False,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai-chat"
    agent.system_prompt = None
    agent.messages = [{"role": "user", "content": "hello"}]
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.tool_declarations = []
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    return agent


def test_openai_responses_api_false_uses_chat_completions():
    agent = _build_openai_chat_agent()
    requests = []

    def fake_post(**kwargs):
        requests.append(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "chat ok"}}]}

    agent._curl_post_json_once = lambda **kwargs: fake_post(**kwargs)

    result = agent.Send(web_search="disabled", thinking="disabled", reasoning_effort="high", stream=False)

    assert result == "chat ok"
    assert requests[0]["url"] == "https://chat.example/v1/chat/completions"
    payload = json.loads(requests[0]["payload_json"])
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
    assert payload["reasoning_effort"] == "high"
    assert "input" not in payload


def test_openai_chat_provider_treats_unsupported_web_search_as_disabled():
    agent = _build_openai_chat_agent()
    requests = []

    def fake_post(**kwargs):
        requests.append(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "chat ok"}}]}

    agent._curl_post_json_once = lambda **kwargs: fake_post(**kwargs)

    assert agent.Send(web_search="enabled", thinking="disabled", stream=False) == "chat ok"
    payload = json.loads(requests[0]["payload_json"])
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
    assert "tools" not in payload
    assert "input" not in payload


def test_openai_chat_provider_treats_unsupported_thinking_as_disabled():
    agent = _build_openai_chat_agent()
    requests = []

    def fake_post(**kwargs):
        requests.append(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "chat ok"}}]}

    agent._curl_post_json_once = lambda **kwargs: fake_post(**kwargs)

    assert agent.Send(web_search="disabled", thinking="enabled", stream=False) == "chat ok"
    payload = json.loads(requests[0]["payload_json"])
    assert "thinking" not in payload
    assert "reasoning" not in payload


def test_openai_chat_compaction_gate_uses_chat_completions_when_responses_api_false():
    from src.tool.tool_call_protocol import ToolCallExecution

    agent = _build_openai_chat_agent()
    agent.config["toolContextCompactionEnabled"] = True
    agent.config["toolContextCompactionEveryToolCalls"] = 1
    agent.messages = [
        {"role": "user", "content": "inspect files"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_read",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "content": "raw file content", "tool_call_id": "call_read", "name": "read_file"},
    ]
    requests = []

    def fake_post(**kwargs):
        requests.append(kwargs)
        payload = json.loads(kwargs["payload_json"])
        assert kwargs["url"] == "https://chat.example/v1/chat/completions"
        assert "input" not in payload
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_compact",
                                "type": "function",
                                "function": {
                                    "name": "compact_tool_context",
                                    "arguments": json.dumps(
                                        {
                                            "action": "replace",
                                            "reason": "The tool output was summarized.",
                                            "summary": "Read the requested file and kept the useful finding.",
                                        }
                                    ),
                                },
                            }
                        ],
                    }
                }
            ]
        }

    agent._curl_post_json_once = lambda **kwargs: fake_post(**kwargs)

    ran = agent._run_tool_context_compaction_gate_if_needed(
        [ToolCallExecution("read_file", "call_read", "raw file content")]
    )

    assert ran is True
    payload = json.loads(requests[0]["payload_json"])
    assert payload["tools"][0]["function"]["name"] == "compact_tool_context"


def test_openai_chat_tool_warnings_do_not_split_parallel_tool_results():
    agent = _build_openai_chat_agent()
    requests = []

    agent.tools.function_map["blocked_tool"] = lambda: {
        "status": "blocked",
        "retryable": False,
        "reason": "blocked for test",
    }
    agent.tools.function_map["ok_tool_a"] = lambda: "a"
    agent.tools.function_map["ok_tool_b"] = lambda: "b"

    def fake_post(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        requests.append(payload)
        if len(requests) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "blocked_tool", "arguments": "{}"},
                                },
                                {
                                    "id": "call_2",
                                    "type": "function",
                                    "function": {"name": "ok_tool_a", "arguments": "{}"},
                                },
                                {
                                    "id": "call_3",
                                    "type": "function",
                                    "function": {"name": "ok_tool_b", "arguments": "{}"},
                                },
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "done"}}]}

    agent._curl_post_json_once = lambda **kwargs: fake_post(**kwargs)

    assert agent.Send(web_search="disabled", thinking="disabled", stream=False) == "done"

    followup_messages = requests[1]["messages"]
    assistant_index = next(index for index, message in enumerate(followup_messages) if message.get("tool_calls"))
    following_roles = [message["role"] for message in followup_messages[assistant_index + 1 : assistant_index + 5]]
    assert following_roles == ["tool", "tool", "tool", "system"]
    assert [
        message.get("tool_call_id")
        for message in followup_messages[assistant_index + 1 : assistant_index + 4]
    ] == ["call_1", "call_2", "call_3"]
