def _build_agent():
    from src.base_tool import BaseTool
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://example.com/v1",
        "model": "doubao-test",
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesApi": True,
    }
    agent.provider_name = "doubao"
    agent.system_prompt = None
    agent.messages = []
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


def test_send_web_search_stream_after_function_call_still_streams_final_text():
    from src.tool_call_protocol import ToolCallExecution

    agent = _build_agent()
    stream_events = []
    response_rounds = []

    def _fake_stream_responses_with_retry(**kwargs):
        response_rounds.append(dict(kwargs))
        handler = kwargs.get("stream_handler")
        if len(response_rounds) == 1:
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
