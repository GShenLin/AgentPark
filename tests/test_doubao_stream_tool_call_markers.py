def _build_agent():
    from src.tool.base_tool import BaseTool
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://example.com/v1",
        "model": "doubao-test",
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesApi": True,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "doubao"
    agent.system_prompt = None
    agent.messages = []
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.tools = BaseTool(agent)
    agent._read_provider_config_from_file = lambda: dict(agent.config)

    def _message(role, content, persist=True, **kwargs):
        msg = {"role": role, "content": content}
        msg.update(kwargs)
        agent.messages.append(msg)

    agent.Message = _message
    agent._get_messages_with_memory = lambda: list(agent.messages)
    return agent


def test_parse_tagged_function_calls_from_text():
    agent = _build_agent()
    result = agent._parse_tagged_function_calls_from_text(
        'prefix <|FunctionCallBegin|>[{"name":"web_search","parameters":{"query":"abc","recent_days":1}}]<|FunctionCallEnd|> suffix'
    )

    assert result.visible_text == "prefix  suffix"
    assert result.diagnostics == ()
    calls = result.calls
    assert isinstance(calls, list) and len(calls) == 1
    first = calls[0]
    assert first["function"]["name"] == "web_search"
    assert first["function"]["arguments"] == '{"query": "abc", "recent_days": 1}'


def test_stream_chat_completions_reads_curl_sse_lines():
    agent = _build_agent()
    events = []

    def _fake_sse_lines(**_kwargs):
        yield '{"choices":[{"delta":{"content":"O"},"index":0}]}'
        yield '{"choices":[{"delta":{"content":"K"},"index":0}]}'
        yield "[DONE]"

    agent._curl_post_sse_data_lines = _fake_sse_lines

    result = agent._stream_chat_completions_once(
        url="https://example.com/v1/chat/completions",
        headers={"Authorization": "Bearer test"},
        payload_json='{"stream": true}',
        timeout_sec=60,
        stream_handler=lambda delta, full: events.append((delta, full)),
    )

    assert result["choices"][0]["message"]["content"] == "OK"
    assert events == [("O", "O"), ("K", "OK")]


def test_stream_chat_completions_forwards_reasoning_content():
    agent = _build_agent()
    stream_events = []
    thinking_events = []

    def _fake_sse_lines(**_kwargs):
        yield '{"choices":[{"delta":{"reasoning_content":"plan ","content":"O"},"index":0}]}'
        yield '{"choices":[{"delta":{"reasoning_content":"then","content":"K"},"index":0}]}'
        yield "[DONE]"

    agent._curl_post_sse_data_lines = _fake_sse_lines

    result = agent._stream_chat_completions_once(
        url="https://example.com/v1/chat/completions",
        headers={"Authorization": "Bearer test"},
        payload_json='{"stream": true}',
        timeout_sec=60,
        stream_handler=lambda delta, full: stream_events.append((delta, full)),
        thinking_stream_handler=lambda delta, full, provider: thinking_events.append((delta, full, provider)),
    )

    assert result["choices"][0]["message"]["content"] == "OK"
    assert stream_events == [("O", "O"), ("K", "OK")]
    assert thinking_events == [("plan ", "plan ", "doubao"), ("then", "plan then", "doubao")]


def test_stream_chat_completions_retry_does_not_forward_item_event_handler():
    agent = _build_agent()
    events = []

    def _fake_sse_lines(**_kwargs):
        yield '{"choices":[{"delta":{"content":"OK"},"index":0}]}'
        yield "[DONE]"

    agent._curl_post_sse_data_lines = _fake_sse_lines

    result = agent._stream_chat_completions_with_retry(
        endpoint="chat/completions",
        url="https://example.com/v1/chat/completions",
        headers={"Authorization": "Bearer test"},
        payload_json='{"stream": true}',
        max_retries=0,
        retry_delay=0,
        stream_handler=lambda delta, full: events.append((delta, full)),
    )

    assert result["choices"][0]["message"]["content"] == "OK"
    assert events == [("OK", "OK")]


def test_stream_responses_retry_forwards_item_event_handler():
    import json

    agent = _build_agent()
    collected = []

    def _fake_sse_lines(**_kwargs):
        yield json.dumps(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "id": "fc-1",
                    "call_id": "call-1",
                    "name": "web_search",
                    "arguments": "{\"query\":\"today\"}",
                },
            }
        )
        yield json.dumps({"type": "response.completed", "response": {"id": "resp-1", "output": []}})

    agent._curl_post_sse_data_lines = _fake_sse_lines

    result = agent._stream_responses_with_retry(
        endpoint="responses",
        url="https://example.com/v1/responses",
        headers={"Authorization": "Bearer test"},
        payload_json='{"stream": true}',
        max_retries=0,
        retry_delay=0,
        stream_handler=None,
        item_event_handler=collected.append,
    )

    assert result["output"][0]["type"] == "function_call"
    assert result["output"][0]["call_id"] == "call-1"
    assert collected


def test_tagged_function_call_parse_reports_malformed_payload():
    agent = _build_agent()

    result = agent._parse_tagged_function_calls_from_text(
        "prefix <|FunctionCallBegin|>{bad json<|FunctionCallEnd|> suffix"
    )

    assert result.visible_text == "prefix  suffix"
    assert result.calls == []
    assert len(result.diagnostics) == 1
    assert "invalid JSON" in result.diagnostics[0]


def test_tagged_function_call_parse_reports_unclosed_marker():
    agent = _build_agent()

    result = agent._parse_tagged_function_calls_from_text("prefix <|FunctionCallBegin|>{}")

    assert result.visible_text == "prefix <|FunctionCallBegin|>{}"
    assert result.calls == []
    assert result.diagnostics == ("tagged function call begin marker has no matching end marker",)


def test_normalize_message_tool_calls_emits_parser_diagnostic_notice():
    agent = _build_agent()
    events = []
    agent.tool_event_callback = events.append

    message = {
        "role": "assistant",
        "content": "prefix <|FunctionCallBegin|>{bad json<|FunctionCallEnd|> suffix",
    }

    normalized = agent._normalize_message_tool_calls(message)

    assert normalized["content"] == "prefix  suffix"
    assert "tool_calls" not in normalized
    assert events
    assert events[0]["type"] == "runtime_notice"
    assert events[0]["source"] == "provider_tool_call_parser"
    assert "invalid JSON" in events[0]["message"]


def test_send_stream_runs_tool_when_marker_only_response():
    agent = _build_agent()
    agent.config["responsesApi"] = False
    send_rounds = []
    executed = []

    def _fake_stream_call(**_kwargs):
        send_rounds.append(len(send_rounds) + 1)
        if len(send_rounds) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '<|FunctionCallBegin|>[{"name":"web_search","parameters":{"query":"today","recent_days":1}}]<|FunctionCallEnd|>',
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "final answer"}}]}

    agent._stream_chat_completions_with_retry = _fake_stream_call
    def web_search(query=None, recent_days=None):
        executed.append(("web_search", {"query": query, "recent_days": recent_days}))
        return '{"status":"ok"}'

    agent.tools.function_map["web_search"] = web_search

    agent.Message("user", "最新新闻", persist=False)
    output = agent.Send(run_tools=True, stream=True)

    assert output == "final answer"
    assert len(send_rounds) == 2
    assert len(executed) == 1
    assert executed[0][0] == "web_search"
    assert executed[0][1] == {"query": "today", "recent_days": 1}


def test_send_stream_returns_tool_submission_size_error_to_model():
    import json

    agent = _build_agent()
    agent.config["responsesApi"] = False
    send_payloads = []
    executed = []

    def _fake_stream_call(**kwargs):
        send_payloads.append(json.loads(kwargs["payload_json"]))
        if len(send_payloads) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "web_search",
                                        "arguments": "{\"query\":\"today\"}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        if len(send_payloads) == 2:
            raise RuntimeError(
                "HTTP Error 400: InvalidParameter: Total tokens of image and text exceed max message tokens."
            )
        return {"choices": [{"message": {"role": "assistant", "content": "我会改用更小范围查询。"}}]}

    def web_search(query=None):
        executed.append(query)
        return "{\"status\":\"success\",\"stdout\":\"" + ("x" * 50000) + "\"}"

    agent._stream_chat_completions_with_retry = _fake_stream_call
    agent.tools.function_map["web_search"] = web_search

    agent.Message("user", "最新新闻", persist=False)
    output = agent.Send(run_tools=True, stream=True)

    assert output == "我会改用更小范围查询。"
    assert executed == ["today"]
    assert len(send_payloads) == 3
    submitted_tool_message = next(
        item for item in send_payloads[1]["messages"] if item.get("role") == "tool"
    )
    submitted_payload = json.loads(submitted_tool_message["content"])
    assert submitted_payload["status"] == "tool_result_submission_error"
    assert submitted_payload["tool"] == "web_search"
    assert submitted_payload["call_id"] == "call-1"
    recovered_tool_message = next(
        item for item in send_payloads[2]["messages"] if item.get("role") == "tool"
    )
    recovered_payload = json.loads(recovered_tool_message["content"])
    assert recovered_payload["status"] == "tool_result_submission_error"
    assert recovered_payload["tool"] == "web_search"
    assert recovered_payload["call_id"] == "call-1"
    assert recovered_payload["original_result_chars"] > 50000
    assert "Total tokens" in recovered_payload["provider_error"]
    notices = [
        event
        for event in agent.events
        if event.get("type") == "runtime_notice"
        and event.get("stage") == "tool_result_submission_compacted"
    ]
    assert len(notices) == 2
    assert all("web_search" in event["message"] for event in notices)
    assert all("call-1" in event["message"] for event in notices)


def test_chat_completions_tool_continuation_appends_mid_turn_user_input():
    import json

    from src.providers.agent_runtime_context import AgentRuntimeContext, bind_agent_runtime_context

    agent = _build_agent()
    agent.config["responsesApi"] = False
    send_payloads = []
    mid_turn_messages = [[{"role": "user", "content": "补充：改查 B。"}]]
    bind_agent_runtime_context(
        agent,
        AgentRuntimeContext(
            graph_id="g1",
            node_id="agent1",
            node_type_id="agent_node",
            consume_mid_turn_user_inputs=lambda: mid_turn_messages.pop(0) if mid_turn_messages else [],
        ),
    )

    def _fake_post_call(**kwargs):
        send_payloads.append(json.loads(kwargs["payload_json"]))
        if len(send_payloads) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "web_search",
                                        "arguments": "{\"query\":\"today\"}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "final answer"}}]}

    def web_search(query=None):
        return f"search:{query}"

    agent._post_json_with_retry = _fake_post_call
    agent.tools.function_map["web_search"] = web_search
    agent.Message("user", "最新新闻", persist=False)

    assert agent.Send(run_tools=True, stream=False) == "final answer"
    assert len(send_payloads) == 2
    assert send_payloads[1]["messages"][-2] == {
        "role": "tool",
        "content": "search:today",
        "tool_call_id": "call-1",
        "name": "web_search",
    }
    assert send_payloads[1]["messages"][-1] == {"role": "user", "content": "补充：改查 B。"}


def test_send_stream_returns_timeout_tool_error_when_tool_messages_are_filtered():
    import json

    from src.base_agent import BaseAgent
    from src.tool.tool_call_protocol import ToolCallExecution

    agent = _build_agent()
    agent.config["responsesApi"] = False
    agent.internal_memory_enabled = False

    class Memory:
        def build_messages_with_memory(self, messages):
            return [dict(item) for item in messages]

    agent.memory = Memory()
    agent._get_messages_with_memory = BaseAgent._get_messages_with_memory.__get__(agent, type(agent))
    send_payloads = []

    def _fake_stream_call(**kwargs):
        send_payloads.append(json.loads(kwargs["payload_json"]))
        if len(send_payloads) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "execute_curl_command",
                                        "arguments": "{\"url\":\"https://gamma.app\"}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "curl 超时了，我换一种方式处理。"}}]}

    agent._stream_chat_completions_with_retry = _fake_stream_call
    agent._execute_tool_calls_parallel = lambda _calls: [
        ToolCallExecution(
            func_name="execute_curl_command",
            call_id="call-1",
            cleaned_result=(
                "{\"status\":\"timeout\",\"tool\":\"execute_curl_command\","
                "\"error\":\"Tool execution exceeded 5.00s.\",\"url\":\"https://gamma.app\"}"
            ),
            image_data=None,
            status="timeout",
            error="Tool execution exceeded 5.00s.",
        )
    ]

    agent.Message("user", "在吗", persist=False)
    output = agent.Send(run_tools=True, stream=True)

    assert output == "curl 超时了，我换一种方式处理。"
    assert len(send_payloads) == 2
    tool_messages = [item for item in send_payloads[1]["messages"] if item.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call-1"
    payload = json.loads(tool_messages[0]["content"])
    assert payload["status"] == "timeout"
    assert payload["tool"] == "execute_curl_command"
    assert payload["error"] == "Tool execution exceeded 5.00s."
    assert payload["url"] == "https://gamma.app"


def test_send_stream_returns_completed_tool_result_when_tool_messages_are_filtered():
    import json

    from src.base_agent import BaseAgent
    from src.tool.tool_call_protocol import ToolCallExecution

    agent = _build_agent()
    agent.config["responsesApi"] = False
    agent.internal_memory_enabled = False

    class Memory:
        def build_messages_with_memory(self, messages):
            return [dict(item) for item in messages]

    agent.memory = Memory()
    agent._get_messages_with_memory = BaseAgent._get_messages_with_memory.__get__(agent, type(agent))
    send_payloads = []

    def _fake_stream_call(**kwargs):
        send_payloads.append(json.loads(kwargs["payload_json"]))
        if len(send_payloads) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "execute_curl_command",
                                        "arguments": "{\"url\":\"https://www.volcengine.com/docs/82379/1925114?lang=zh\"}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "火山文档内容已读取。"}}]}

    tool_result = (
        "{\"status\":\"completed\",\"tool\":\"execute_curl_command\","
        "\"url\":\"https://www.volcengine.com/docs/82379/1925114?lang=zh\","
        "\"stdout\":\"<html>火山 Coding Plan 说明</html>\",\"returncode\":0}"
    )
    agent._stream_chat_completions_with_retry = _fake_stream_call
    agent._execute_tool_calls_parallel = lambda _calls: [
        ToolCallExecution(
            func_name="execute_curl_command",
            call_id="call-1",
            cleaned_result=tool_result,
            image_data=None,
        )
    ]

    agent.Message("user", "你看看火山 Coding Plan的具体限制和内容", persist=False)
    output = agent.Send(run_tools=True, stream=True)

    assert output == "火山文档内容已读取。"
    assert len(send_payloads) == 2
    tool_messages = [item for item in send_payloads[1]["messages"] if item.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0]["tool_call_id"] == "call-1"
    assert tool_messages[0]["name"] == "execute_curl_command"
    assert "火山 Coding Plan 说明" in tool_messages[0]["content"]


def test_send_web_search_stream_after_function_call_still_streams_final_text():
    from src.providers.openai_responses_stream_normalizer import OpenAIResponsesStreamEventNormalizer
    from src.tool.tool_call_protocol import ToolCallExecution

    agent = _build_agent()
    stream_events = []
    response_rounds = []

    def _fake_stream_responses_with_retry(**kwargs):
        response_rounds.append(dict(kwargs))
        handler = kwargs.get("stream_handler")
        item_handler = kwargs.get("item_event_handler")
        if len(response_rounds) == 1:
            normalizer = OpenAIResponsesStreamEventNormalizer(provider="doubao_responses")
            for event in normalizer.ingest_event(
                {
                    "type": "response.output_item.done",
                    "item": {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "web_search",
                        "arguments": "{\"query\":\"today\",\"recent_days\":1}",
                    },
                }
            ):
                item_handler(event)
            return {
                "id": "resp-call",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "web_search",
                        "arguments": "{\"query\":\"today\",\"recent_days\":1}",
                    }
                ],
            }
        if callable(handler):
            handler("今", "今")
            handler("天", "今天")
        return {
            "id": "resp-final",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "今天"}],
                }
            ],
        }

    agent._stream_responses_with_retry = _fake_stream_responses_with_retry
    agent._post_json_with_retry = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("streaming responses path should be used")
    )
    agent._execute_tool_calls_parallel = lambda _calls: [
        ToolCallExecution(
            func_name="web_search",
            call_id="call-1",
            cleaned_result="{\"status\":\"ok\"}",
            image_data=None,
        )
    ]

    agent.Message("user", "今天热点", persist=False)
    out = agent.Send(
        run_tools=True,
        web_search="enabled",
        stream=True,
        stream_handler=lambda delta, full: stream_events.append((str(delta), str(full))),
    )

    assert out == "今天"
    assert len(response_rounds) == 2
    assert len(stream_events) >= 2
    assert stream_events[0] == ("今", "今")
    assert stream_events[1] == ("天", "今天")


def test_send_web_search_stream_uses_stream_text_when_result_is_metadata_only():
    agent = _build_agent()
    stream_events = []

    def _fake_stream_responses_with_retry(**kwargs):
        handler = kwargs.get("stream_handler")
        if callable(handler):
            handler("成", "成")
            handler("都", "成都")
            handler("天气晴", "成都天气晴")
        return {
            "id": "resp_meta_only",
            "created_at": 1772263795,
            "model": "doubao-seed-2-0-pro-260215",
            "object": "response",
            "max_output_tokens": 32768,
        }

    agent._stream_responses_with_retry = _fake_stream_responses_with_retry
    agent._post_json_with_retry = lambda **_kwargs: (_ for _ in ()).throw(
        AssertionError("streaming responses path should be used")
    )

    agent.Message("user", "查询今天成都天气", persist=False)
    out = agent.Send(
        run_tools=True,
        web_search="enabled",
        stream=True,
        stream_handler=lambda delta, full: stream_events.append((str(delta), str(full))),
    )

    assert out == "成都天气晴"
    assert stream_events[-1] == ("天气晴", "成都天气晴")
