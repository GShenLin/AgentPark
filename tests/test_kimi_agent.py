import json

import pytest

from src.provider_feature_matrix import build_provider_feature_matrix


def _build_kimi_agent(*, model="kimi-k3"):
    from src.providers.kimi_agent import KimiAgent
    from src.tool.base_tool import BaseTool

    agent = KimiAgent.__new__(KimiAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://api.moonshot.cn/v1",
        "model": model,
        "responsesApi": False,
        "features": build_provider_feature_matrix({"type": "kimi", "model": model}),
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "kimi"
    agent.system_prompt = None
    agent.messages = [{"role": "user", "content": "search today's news"}]
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.tool_declarations = []
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    return agent


def test_kimi_k3_web_search_uses_builtin_function_and_echoes_arguments():
    agent = _build_kimi_agent()
    requests = []
    events = []
    search_arguments = '{"query":"today news","usage":{"total_tokens":321}}'
    responses = iter(
        [
            {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning_content": "Need current information.",
                            "tool_calls": [
                                {
                                    "id": "kimi-search-1",
                                    "type": "function",
                                    "function": {
                                        "name": "$web_search",
                                        "arguments": search_arguments,
                                    },
                                }
                            ],
                        },
                    }
                ]
            },
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "Search complete.",
                            "reasoning_content": "Summarized the search results.",
                        },
                    }
                ]
            },
        ]
    )

    def fake_post(**kwargs):
        requests.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent.tool_event_callback = lambda event: events.append(event)
    agent._curl_post_json_once = fake_post

    result = agent.Send(
        web_search="enabled",
        thinking="disabled",
        reasoning_effort="max",
        stream=False,
    )

    assert result == "Search complete."
    assert len(requests) == 2
    expected_tool = {"type": "builtin_function", "function": {"name": "$web_search"}}
    assert expected_tool in requests[0]["tools"]
    assert expected_tool in requests[1]["tools"]
    assert requests[0]["reasoning_effort"] == "max"
    assert "thinking" not in requests[0]
    assert requests[1]["messages"][-2]["reasoning_content"] == "Need current information."
    assert requests[1]["messages"][-1] == {
        "role": "tool",
        "content": search_arguments,
        "tool_call_id": "kimi-search-1",
        "name": "$web_search",
    }
    search_events = [event for event in events if event.get("type") == "server_tool_activity"]
    assert [(event["call_id"], event["status"]) for event in search_events] == [
        ("kimi-search-1", "in_progress"),
        ("kimi-search-1", "completed"),
    ]
    assert search_events[0]["action"] == {"query": "today news"}
    assert agent.messages[-1]["reasoning_content"] == "Summarized the search results."


def test_kimi_web_search_coexists_with_regular_function_tools():
    agent = _build_kimi_agent()
    agent.tool_declarations = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    requests = []
    agent._curl_post_json_once = lambda **kwargs: (
        requests.append(json.loads(kwargs["payload_json"]))
        or {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
    )

    assert agent.Send(web_search="enabled", thinking="disabled", reasoning_effort="max") == "ok"
    assert [item["type"] for item in requests[0]["tools"]] == ["function", "builtin_function"]


def test_kimi_stream_replays_reasoning_content_across_web_search():
    agent = _build_kimi_agent()
    requests = []
    streams = iter(
        [
            [
                '{"choices":[{"delta":{"reasoning_content":"Need current news.","tool_calls":[{"index":0,"id":"kimi-search-stream","type":"function","function":{"name":"$web_search","arguments":"{\\"query\\":\\"today news\\"}"}}]}}]}',
                "[DONE]",
            ],
            [
                '{"choices":[{"delta":{"reasoning_content":"Summarize sources."}}]}',
                '{"choices":[{"delta":{"content":"done"}}]}',
                "[DONE]",
            ],
        ]
    )

    def fake_stream(**kwargs):
        requests.append(json.loads(kwargs["payload_json"]))
        return iter(next(streams))

    agent._curl_post_sse_data_lines = fake_stream

    assert agent.Send(
        web_search="enabled",
        thinking="disabled",
        reasoning_effort="max",
        stream=True,
    ) == "done"
    assert requests[1]["messages"][-2]["reasoning_content"] == "Need current news."
    assert requests[1]["messages"][-1]["name"] == "$web_search"
    assert agent.messages[-1]["reasoning_content"] == "Summarize sources."


def test_kimi_groups_parallel_tool_results_before_runtime_warnings():
    agent = _build_kimi_agent()
    agent.tool_declarations = [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": name,
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in ("blocked_tool", "ok_tool")
    ]
    agent.tools.function_map["blocked_tool"] = lambda: {
        "status": "blocked",
        "retryable": False,
        "reason": "blocked for test",
    }
    agent.tools.function_map["ok_tool"] = lambda: "ok"
    requests = []

    def fake_post(**kwargs):
        requests.append(json.loads(kwargs["payload_json"]))
        if len(requests) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-blocked",
                                    "type": "function",
                                    "function": {"name": "blocked_tool", "arguments": "{}"},
                                },
                                {
                                    "id": "call-ok",
                                    "type": "function",
                                    "function": {"name": "ok_tool", "arguments": "{}"},
                                },
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "done"}}]}

    agent._curl_post_json_once = fake_post

    assert agent.Send(web_search="disabled", thinking="disabled", reasoning_effort="max") == "done"
    followup = requests[1]["messages"]
    assistant_index = next(index for index, message in enumerate(followup) if message.get("tool_calls"))
    assert [message["role"] for message in followup[assistant_index + 1 : assistant_index + 4]] == [
        "tool",
        "tool",
        "system",
    ]
    assert [
        message.get("tool_call_id")
        for message in followup[assistant_index + 1 : assistant_index + 3]
    ] == ["call-blocked", "call-ok"]


def test_kimi_k3_rejects_unsupported_reasoning_effort():
    agent = _build_kimi_agent()
    agent._curl_post_json_once = lambda **_kwargs: pytest.fail("request must not be sent")

    with pytest.raises(ValueError, match="supports only 'max'"):
        agent.Send(web_search="disabled", thinking="disabled", reasoning_effort="high")


def test_kimi_k26_web_search_requires_disabled_thinking():
    agent = _build_kimi_agent(model="kimi-k2.6")
    agent._curl_post_json_once = lambda **_kwargs: pytest.fail("request must not be sent")

    with pytest.raises(ValueError, match=r"\$web_search requires thinking=disabled"):
        agent.Send(web_search="enabled", thinking="enabled", reasoning_effort="")
