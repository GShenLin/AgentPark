import json

import pytest

from src.tool.base_tool import BaseTool
from src.providers.tool_call_runtime import ToolCallExecutionRuntime
from src.providers.zhipu_agent import ZhipuAgent
from src.providers.zhipu_chat_runtime import ZhipuChatRuntime
from src.providers.zhipu_http_transport import ZhipuHttpError


def _make_zhipu_agent():
    agent = ZhipuAgent.__new__(ZhipuAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-test",
        "maxRetries": 0,
        "retryDelaySec": 0,
        "timeoutMs": 1000,
    }
    agent.provider_name = "zhipu"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.system_prompt = None
    agent.internal_memory_enabled = False
    agent.tool_event_callback = None
    agent._service_targets_cache = (
        ToolCallExecutionRuntime(agent),
        ZhipuChatRuntime(agent),
    )
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    return agent


def test_zhipu_send_uses_chat_completions_payload_and_endpoint():
    agent = _make_zhipu_agent()
    agent.config.update(
        {
            "thinking": "enabled",
            "clearThinking": "false",
            "maxTokens": "128",
            "temperature": 0.2,
            "top_p": 0.9,
            "stop": ["END"],
            "doSample": True,
            "toolStream": True,
            "responseFormat": {"type": "json_object"},
            "toolChoice": "auto",
            "requestId": "request-123",
            "userId": "user-123",
        }
    )
    agent.messages = [{"role": "user", "content": "hello"}]
    requests = []
    tools = [{"type": "function", "function": {"name": "echo_tool", "parameters": {"type": "object"}}}]

    def fake_stream(**kwargs):
        requests.append(kwargs)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}]}

    agent._stream_chat_completions_with_retry = fake_stream

    out = agent.Send(
        tools=tools,
        run_tools=False,
        thinking="enabled",
        reasoning_effort="medium",
        stream=True,
        stream_handler=lambda _delta, _full: None,
    )

    assert out == "ok"
    assert len(requests) == 1
    assert requests[0]["url"] == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert "/responses" not in requests[0]["url"]
    assert requests[0]["headers"]["Authorization"] == "Bearer test-key"
    payload = json.loads(requests[0]["payload_json"])
    assert payload["model"] == "glm-test"
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
    assert payload["tools"] == tools
    assert payload["stream"] is True
    assert payload["reasoning_effort"] == "medium"
    assert payload["thinking"] == {"type": "enabled", "clear_thinking": False}
    assert payload["max_tokens"] == 128
    assert payload["temperature"] == 0.2
    assert payload["top_p"] == 0.9
    assert payload["stop"] == ["END"]
    assert payload["do_sample"] is True
    assert payload["tool_stream"] is True
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["tool_choice"] == "auto"
    assert payload["request_id"] == "request-123"
    assert payload["user_id"] == "user-123"


def test_zhipu_tool_call_continuation_uses_chat_messages():
    agent = _make_zhipu_agent()
    agent.messages = [{"role": "user", "content": "run echo"}]
    captured = []
    requests = []

    def echo_tool(message=None):
        captured.append(message)
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool

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
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "echo_tool", "arguments": '{"message":"hello"}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}
                ]
            },
        ]
    )

    def fake_post(**kwargs):
        requests.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post

    out = agent.Send(run_tools=True)

    assert out == "done"
    assert captured == ["hello"]
    assert len(requests) == 2
    assert requests[1]["messages"][0] == {"role": "user", "content": "run echo"}
    assert requests[1]["messages"][1]["role"] == "assistant"
    assert requests[1]["messages"][1]["tool_calls"][0]["id"] == "call-1"
    assert requests[1]["messages"][2] == {
        "role": "tool",
        "content": "echo:hello",
        "tool_call_id": "call-1",
        "name": "echo_tool",
    }


def test_zhipu_tool_context_compaction_runs_between_tool_rounds():
    agent = _make_zhipu_agent()
    agent.config.update({
        "toolContextCompactionEnabled": True,
        "toolContextCompactionEveryToolCalls": 1,
    })
    agent.tool_context_compaction_gate_enabled = True
    agent._tool_context_compaction_since_last = 0
    agent.messages = [{"role": "user", "content": "run echo"}]
    requests = []

    def echo_tool(message=None):
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool

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
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {"name": "echo_tool", "arguments": '{"message":"hello"}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "compact-1",
                                    "type": "function",
                                    "function": {
                                        "name": "compact_tool_context",
                                        "arguments": json.dumps(
                                            {
                                                "action": "replace",
                                                "reason": "The first tool result was summarized.",
                                                "summary": "echo_tool returned echo:hello.",
                                            }
                                        ),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}
                ]
            },
        ]
    )

    def fake_post(**kwargs):
        requests.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post

    assert agent.Send(run_tools=True) == "done"
    assert len(requests) == 3
    gate_messages = requests[1]["messages"]
    assert "Tool calls have accumulated" in gate_messages[-1]["content"]
    final_messages = requests[2]["messages"]
    final_text = json.dumps(final_messages, ensure_ascii=False)
    assert "Tool calls have accumulated" not in final_text
    assert "compact_tool_context" not in final_text
    assert "echo_tool returned echo:hello" in final_text
    assert "echo:hello" not in [item.get("content") for item in final_messages if item.get("role") == "tool"]


def test_zhipu_invalid_tool_arguments_return_typed_tool_result():
    agent = _make_zhipu_agent()
    agent.messages = [{"role": "user", "content": "patch"}]
    requests = []

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
                                    "id": "call-bad",
                                    "type": "function",
                                    "function": {
                                        "name": "apply_patch",
                                        "arguments": '{"patch":"*** Begin Patch\n*** End Patch"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            {
                "choices": [
                    {"message": {"role": "assistant", "content": "fixed"}, "finish_reason": "stop"}
                ]
            },
        ]
    )

    def fake_post(**kwargs):
        requests.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post

    assert agent.Send(run_tools=True) == "fixed"
    tool_message = requests[1]["messages"][2]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call-bad"
    payload = json.loads(tool_message["content"])
    assert payload["status"] == "invalid_arguments"
    assert payload["call_id"] == "call-bad"
    assert "failed to parse tool arguments JSON" in payload["error"]


def test_zhipu_stream_assembles_text_and_tool_call_deltas():
    agent = _make_zhipu_agent()
    seen = []
    events = [
        {"choices": [{"delta": {"content": "hel"}}]},
        {"choices": [{"delta": {"content": "lo"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "echo_tool", "arguments": '{"message":'},
                            }
                        ]
                    }
                }
            ]
        },
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"hi"}'}}]}}]},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]

    agent._curl_post_sse_data_lines = lambda **_kwargs: (json.dumps(event) for event in events)

    result = agent._stream_chat_completions_once(
        url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
        headers={},
        payload_json="{}",
        stream_handler=lambda delta, full: seen.append((delta, full)),
    )

    message = result["choices"][0]["message"]
    assert seen == [("hel", "hel"), ("lo", "hello")]
    assert message["content"] == "hello"
    assert message["tool_calls"] == [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "echo_tool", "arguments": '{"message":"hi"}'},
        }
    ]


def test_zhipu_rejects_unsupported_thinking_auto():
    agent = _make_zhipu_agent()
    agent.messages = [{"role": "user", "content": "hello"}]

    with pytest.raises(ValueError, match="enabled or disabled"):
        agent.Send(thinking="auto", run_tools=False)


def test_zhipu_quota_429_does_not_retry():
    agent = _make_zhipu_agent()
    agent.config.update({"maxRetries": 5, "retryDelaySec": 0})
    calls = {"count": 0}

    def fake_post_once(**_kwargs):
        calls["count"] += 1
        raise ZhipuHttpError(
            429,
            json.dumps({"error": {"code": "AccountQuotaExceeded", "message": "usage quota exceeded"}}),
        )

    agent._post_json_once = fake_post_once

    with pytest.raises(RuntimeError, match="AccountQuotaExceeded"):
        agent._post_json_with_retry(
            endpoint="chat/completions",
            url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
            headers={},
            payload_json="{}",
        )

    assert calls["count"] == 1
