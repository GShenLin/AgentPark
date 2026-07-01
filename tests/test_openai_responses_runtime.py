import json

from src.tool.base_tool import BaseTool
from src.tool.tool_call_protocol import ToolCallExecution


def _runtime_notice_payloads(events, stage):
    return [
        json.loads(event["message"])
        for event in events
        if event.get("type") == "runtime_notice" and event.get("stage") == stage
    ]


def test_responses_input_uses_output_text_for_assistant_history():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {}
    agent.provider_name = "openai"

    payload = agent._build_responses_input(
        [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {
                "role": "assistant",
                "content": [
                    {"type": "input_text", "text": "old assistant text"},
                    {"type": "refusal", "refusal": "blocked"},
                ],
            },
        ]
    )

    assert [item["type"] for item in payload] == ["message", "message", "message", "message"]
    assert [item["status"] for item in payload] == ["completed", "completed", "completed", "completed"]
    assert payload[0]["content"] == [{"type": "input_text", "text": "system prompt"}]
    assert payload[1]["content"] == [{"type": "input_text", "text": "hello"}]
    assert payload[2]["content"] == [{"type": "output_text", "text": "hi"}]
    assert payload[3]["content"] == [
        {"type": "output_text", "text": "old assistant text"},
        {"type": "refusal", "refusal": "blocked"},
    ]


def test_responses_input_tool_history_items_include_completed_status():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {}
    agent.provider_name = "openai"

    payload = agent._build_responses_input(
        [
            {
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
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "name": "echo_tool",
                "content": "echo:hello",
            },
        ]
    )

    assert payload == [
        {
            "type": "function_call",
            "call_id": "call-1",
            "name": "echo_tool",
            "arguments": '{"message":"hello"}',
            "status": "completed",
        },
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": "echo:hello",
            "status": "completed",
        },
    ]


def test_responses_payload_summary_does_not_mask_missing_input_type():
    from src.providers.openai_transport import OpenAITransport

    summary = OpenAITransport._summarize_responses_payload(
        json.dumps(
            {
                "model": "test",
                "input": [
                    {"role": "user", "content": [{"type": "input_text", "text": "hello"}]},
                    {"type": "message", "role": "assistant", "status": "completed"},
                ],
            }
        )
    )

    assert summary["input"][0]["type"] == ""
    assert summary["input"][0]["type_present"] is False
    assert summary["input"][1]["type"] == "message"
    assert summary["input"][1]["type_present"] is True


def test_openai_responses_payload_includes_web_search_when_enabled():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesContinuationMode": "previous_response_id",
        "responsesReplayReasoningItems": False,
        "webSearchContextSize": "high",
        "webSearchUserLocation": {"type": "approximate", "country": "US", "city": "Seattle"},
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "ok"}],
                }
            ]
        }

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "search latest news"}],
        active_tools=[],
        run_tools=False,
        reasoning_effort="",
        web_search_mode="enabled",
    )

    assert out == "ok"
    assert payloads[0]["tools"] == [
        {
            "type": "web_search",
            "user_location": {"type": "approximate", "country": "US", "city": "Seattle"},
            "search_context_size": "high",
        }
    ]


def test_openai_send_uses_web_search_switch():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesContinuationMode": "previous_response_id",
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.system_prompt = None
    agent.messages = [{"role": "user", "content": "search"}]
    agent.tools = BaseTool(agent)
    agent.tool_declarations = []
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "ok"}],
                }
            ]
        }

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent.Send(run_tools=False, web_search="enabled") == "ok"
    assert payloads[0]["tools"] == [{"type": "web_search"}]


def test_openai_responses_requires_explicit_continuation_mode():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }

    try:
        agent._responses_continuation_mode()
    except ValueError as exc:
        assert "provider.responsesContinuationMode is required" in str(exc)
    else:
        raise AssertionError("missing responsesContinuationMode should fail")


def test_openai_responses_continuation_mode_rejects_aliases():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "responses_continuation_mode": "explicit_context",
        "responsesReplayReasoningItems": False,
    }

    try:
        agent._responses_continuation_mode()
    except ValueError as exc:
        assert "provider.responsesContinuationMode is required" in str(exc)
    else:
        raise AssertionError("snake_case responses continuation key should fail")

    agent.config = {
        "responsesContinuationMode": "explicit",
        "responsesReplayReasoningItems": False,
    }
    try:
        agent._responses_continuation_mode()
    except ValueError as exc:
        assert "must be 'previous_response_id' or 'explicit_context'" in str(exc)
    else:
        raise AssertionError("short responses continuation value should fail")


def test_openai_responses_requires_explicit_reasoning_replay_policy():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesContinuationMode": "explicit_context",
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }

    try:
        agent._responses_replay_reasoning_items()
    except ValueError as exc:
        assert "provider.responsesReplayReasoningItems is required" in str(exc)
    else:
        raise AssertionError("missing responsesReplayReasoningItems should fail")


def test_openai_responses_reasoning_replay_policy_rejects_alias_key():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "responsesContinuationMode": "explicit_context",
        "responses_replay_reasoning_items": False,
    }

    try:
        agent._responses_replay_reasoning_items()
    except ValueError as exc:
        assert "provider.responsesReplayReasoningItems is required" in str(exc)
    else:
        raise AssertionError("snake_case reasoning replay key should fail")


def test_stream_does_not_return_stale_tool_call_intro():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesContinuationMode": "previous_response_id",
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []
    stream_events = []

    def fake_stream(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        handler = kwargs.get("stream_handler")
        if len(payloads) == 1:
            if callable(handler):
                handler("tool intro", "tool intro")
            return {
                "id": "resp-1",
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
        return {
            "id": "resp-2",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "rg returned README.md."}],
                }
            ],
        }

    agent._stream_responses_with_retry = fake_stream
    agent._execute_tool_call_envelopes_parallel = lambda _calls: [
        ToolCallExecution(
            func_name="rg_list_files",
            call_id="call-1",
            cleaned_result='{"status":"success","files":["README.md"]}',
            image_data=None,
        )
    ]

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "run rg"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="medium",
        stream_handler=lambda delta, full: stream_events.append((delta, full)),
    )

    assert out == "rg returned README.md."
    assert len(payloads) == 2
    assert payloads[1]["input"][-1]["type"] == "function_call_output"
    assert payloads[1]["input"][-1]["call_id"] == "call-1"
    assert "README.md" in payloads[1]["input"][-1]["output"]


def test_openai_responses_empty_output_feeds_back_error_before_returning_final_message():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesContinuationMode": "previous_response_id",
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []

    def fake_stream(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        if len(payloads) == 1:
            return {"id": "resp-empty", "output": []}
        return {
            "id": "resp-final",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Recovered after feedback."}],
                }
            ],
        }

    agent._stream_responses_with_retry = fake_stream

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "say something"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="medium",
        stream_handler=lambda _delta, _full: None,
    )

    assert out == "Recovered after feedback."
    assert len(payloads) == 2
    feedback_text = payloads[1]["input"][-1]["content"][0]["text"]
    assert feedback_text.startswith("Error: EmptyMessage\n")
    feedback_payload = json.loads(feedback_text.split("\n", 1)[1])
    assert feedback_payload["error"] == "EmptyMessage"
    assert "input" in feedback_payload
    assert "item" in feedback_payload
    assert feedback_payload["input"]["count"] == 1
    assert feedback_payload["item"]["count"] == 0


def test_openai_responses_empty_output_feedback_uses_compact_recovery_input_after_tool_output():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesContinuationMode": "explicit_context",
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []
    large_output = "asset-row-" * 200000

    def fake_stream(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        payloads.append(payload)
        if len(payloads) == 1:
            return {
                "id": "resp-tool",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "read_large_asset",
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
                    "content": [{"type": "output_text", "text": "Recovered from compact feedback."}],
                }
            ],
        }

    agent._stream_responses_with_retry = fake_stream
    agent._execute_tool_call_envelopes_parallel = lambda _calls: [
        ToolCallExecution(
            func_name="read_large_asset",
            call_id="call-1",
            cleaned_result=large_output,
            image_data=None,
        )
    ]

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "inspect DA_Action_Book"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="medium",
        stream_handler=lambda _delta, _full: None,
    )

    assert out == "Recovered from compact feedback."
    assert len(payloads) == 3
    feedback_input = payloads[2]["input"]
    assert len(feedback_input) == 2
    assert feedback_input[0]["content"][0]["text"].startswith("[Agent Environment Context]\n")
    feedback_text = feedback_input[1]["content"][0]["text"]
    assert len(json.dumps(feedback_input, ensure_ascii=False)) < 10000
    assert "inspect DA_Action_Book" in feedback_text
    assert "tool_result_submission_error" in feedback_text
    assert "asset-row-" not in feedback_text
    feedback_payload = json.loads(feedback_text.split("\n", 1)[1])
    diagnostics = feedback_payload["diagnostics"]
    assert diagnostics["likely_cause"] == "compacted_large_tool_result_context"
    assert diagnostics["largest_tool_result_chars"] > 0
    assert diagnostics["provider_request"]["input_item_count"] == 4
    request_summaries = _runtime_notice_payloads(agent.events, "openai_responses_request_summary")
    assert len(request_summaries) == 3
    assert request_summaries[1]["largest_tool_result"]["call_id"] == "call-1"
    assert request_summaries[1]["largest_tool_result"]["name"] == "read_large_asset"
    assert request_summaries[1]["largest_tool_result"]["output_status"] == "tool_result_submission_error"


def test_openai_responses_empty_output_twice_returns_explicit_error():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesContinuationMode": "previous_response_id",
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []

    def fake_stream(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return {"id": f"resp-{len(payloads)}", "output": []}

    agent._stream_responses_with_retry = fake_stream

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "say something"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="medium",
        stream_handler=lambda _delta, _full: None,
    )

    assert out.startswith("Error: EmptyMessage:")
    assert len(payloads) == 2
    second_text = payloads[1]["input"][-1]["content"][0]["text"]
    assert second_text.startswith("Error: EmptyMessage\n")
    error_payload = json.loads(out.split(": ", 2)[2])
    assert "input" in error_payload
    assert "item" in error_payload
    turn_events = _runtime_notice_payloads(agent.events, "openai_responses_turn")
    assert [event["next_continuation_mode"] for event in turn_events] == [
        "empty_message_feedback",
        "empty_message_error",
    ]


def test_openai_responses_continuation_includes_tool_image_data():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesContinuationMode": "previous_response_id",
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        if len(payloads) == 1:
            return {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "capture_screenshot",
                        "arguments": "{}",
                    }
                ],
            }
        return {
            "id": "resp-2",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "I can see the screenshot."}],
                }
            ],
        }

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post
    agent._execute_tool_call_envelopes_parallel = lambda _calls: [
        ToolCallExecution(
            func_name="capture_screenshot",
            call_id="call-1",
            cleaned_result='{"status":"success","base64_image":"<base64_image_data_truncated>"}',
            image_data={"base64": "YWJj", "path": "", "mime_type": "image/png"},
        )
    ]

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "look at the screen"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
    )

    assert out == "I can see the screenshot."
    assert len(payloads) == 2
    assert payloads[1]["input"][-2]["type"] == "function_call_output"
    image_item = payloads[1]["input"][-1]
    assert image_item["role"] == "user"
    assert image_item["content"][0] == {"type": "input_text", "text": "Image captured by tool."}
    assert image_item["content"][1] == {
        "type": "input_image",
        "image_url": "data:image/png;base64,YWJj",
    }


def test_explicit_context_continuation_replays_user_task_across_multi_tool_rounds():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesContinuationMode": "explicit_context",
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    calls = []
    payloads = []

    def record_probe_call(index=None):
        calls.append(index)
        return json.dumps({"index": index, "status": "ok"}, ensure_ascii=False)

    agent.tools.function_map["record_probe_call"] = record_probe_call

    def fake_post(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        payloads.append(payload)
        if len(payloads) <= 5:
            return {
                "id": f"resp-{len(payloads)}",
                "output": [
                    {
                        "type": "function_call",
                        "id": f"fc-{len(payloads)}",
                        "call_id": f"call-{len(payloads)}",
                        "name": "record_probe_call",
                        "arguments": json.dumps({"index": len(payloads)}),
                        "status": "completed",
                    }
                ],
            }
        return {
            "id": "resp-final",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "KRILL_TOOL_LOOP_DONE: 1,2,3,4,5"}],
                }
            ],
        }

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "call tools five times"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
    )

    assert out == "KRILL_TOOL_LOOP_DONE: 1,2,3,4,5"
    assert calls == [1, 2, 3, 4, 5]
    assert len(payloads) == 6
    for index, payload in enumerate(payloads[1:], start=1):
        assert "previous_response_id" not in payload
        payload_text = json.dumps(payload["input"], ensure_ascii=False)
        assert "call tools five times" in payload_text
        for completed in range(1, index + 1):
            assert f"call-{completed}" in payload_text
            assert f'\\"index\\": {completed}' in payload_text

    turn_events = _runtime_notice_payloads(agent.events, "openai_responses_turn")
    assert [event["next_continuation_mode"] for event in turn_events[:5]] == ["explicit_context"] * 5
    assert turn_events[-1]["next_continuation_mode"] == "final_message"


def test_explicit_context_continuation_omits_reasoning_items_by_default():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesContinuationMode": "explicit_context",
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []
    agent.tools.function_map["echo_tool"] = lambda message=None: f"echo:{message}"

    responses = iter(
        [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "reasoning",
                        "id": "rs-1",
                        "summary": [{"type": "summary_text", "text": "Need one echo call."}],
                    },
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "echo_tool",
                        "arguments": '{"message":"hello"}',
                        "status": "completed",
                    },
                ],
            },
            {
                "id": "resp-final",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "done"}],
                    }
                ],
            },
        ]
    )

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
    ) == "done"

    assert "previous_response_id" not in payloads[1]
    assert all(item.get("type") != "reasoning" for item in payloads[1]["input"])
    function_index = next(index for index, item in enumerate(payloads[1]["input"]) if item.get("type") == "function_call")
    assert payloads[1]["input"][function_index + 1] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": "echo:hello",
        "status": "completed",
    }


def test_responses_invalid_tool_arguments_return_tool_error_and_continue():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesContinuationMode": "explicit_context",
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []

    responses = iter(
        [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-bad",
                        "name": "echo_tool",
                        "arguments": '{"message":',
                        "status": "completed",
                    },
                ],
            },
            {
                "id": "resp-final",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "fixed"}],
                    }
                ],
            },
        ]
    )

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
    ) == "fixed"

    tool_message = agent.messages[1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call-bad"
    tool_payload = json.loads(tool_message["content"])
    assert tool_payload["status"] == "invalid_arguments"
    assert "failed to parse tool arguments JSON" in tool_payload["error"]
    function_index = next(index for index, item in enumerate(payloads[1]["input"]) if item.get("type") == "function_call")
    assert payloads[1]["input"][function_index]["call_id"] == "call-bad"
    assert payloads[1]["input"][function_index + 1]["type"] == "function_call_output"
    output_payload = json.loads(payloads[1]["input"][function_index + 1]["output"])
    assert output_payload["status"] == "invalid_arguments"


def test_explicit_context_continuation_can_replay_reasoning_items_when_enabled():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesContinuationMode": "explicit_context",
        "responsesReplayReasoningItems": True,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []
    agent.tools.function_map["echo_tool"] = lambda message=None: f"echo:{message}"

    responses = iter(
        [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "reasoning",
                        "id": "rs-1",
                        "summary": [{"type": "summary_text", "text": "Need one echo call."}],
                    },
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "echo_tool",
                        "arguments": '{"message":"hello"}',
                        "status": "completed",
                    },
                ],
            },
            {
                "id": "resp-final",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "done"}],
                    }
                ],
            },
        ]
    )

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
    ) == "done"

    reasoning_index = next(index for index, item in enumerate(payloads[1]["input"]) if item.get("type") == "reasoning")
    assert payloads[1]["input"][reasoning_index] == {
        "type": "reasoning",
        "id": "rs-1",
        "summary": [{"type": "summary_text", "text": "Need one echo call."}],
    }
    assert payloads[1]["input"][reasoning_index + 1]["type"] == "function_call"
    assert payloads[1]["input"][reasoning_index + 2] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": "echo:hello",
        "status": "completed",
    }


def test_stream_continues_after_tool_call_without_response_id():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesContinuationMode": "previous_response_id",
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []

    def fake_stream(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        if len(payloads) == 1:
            return {
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "rg_list_files",
                        "arguments": "{}",
                    },
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "I am continuing with rg."}],
                    },
                ],
            }
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "rg returned README.md."}],
                }
            ],
        }

    agent._stream_responses_with_retry = fake_stream
    agent._execute_tool_call_envelopes_parallel = lambda _calls: [
        ToolCallExecution(
            func_name="rg_list_files",
            call_id="call-1",
            cleaned_result='{"status":"success","files":["README.md"]}',
            image_data=None,
        )
    ]

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "run rg"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="medium",
        stream_handler=lambda _delta, _full: None,
    )

    assert out == "rg returned README.md."
    assert len(payloads) == 2
    assert payloads[1]["input"][-1]["type"] == "function_call_output"
    assert payloads[1]["input"][-1]["call_id"] == "call-1"
    assert "README.md" in payloads[1]["input"][-1]["output"]


def test_responses_requests_include_fresh_environment_context_without_memory_persistence(monkeypatch, tmp_path):
    from src.providers.openai_agent import OpenAIAgent
    import src.providers.agent_environment_context as environment_context

    request_times = iter(
        [
            "2026-06-30T09:00:00+08:00",
            "2026-06-30T09:00:01+08:00",
        ]
    )

    def fake_context(agent, *, current_input=None):
        _ = current_input
        return {
            "workspace_root": str(tmp_path),
            "working_path": str(tmp_path / "work"),
            "shell": "powershell",
            "request_time": next(request_times),
        }

    monkeypatch.setattr(environment_context, "build_agent_environment_context", fake_context)
    monkeypatch.setattr("src.providers.responses_runtime.build_agent_environment_context", fake_context)

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesContinuationMode": "explicit_context",
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []
    agent.tools.function_map["echo_tool"] = lambda message=None: f"echo:{message}"

    responses = iter(
        [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "echo_tool",
                        "arguments": '{"message":"hello"}',
                        "status": "completed",
                    },
                ],
            },
            {
                "id": "resp-final",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "done"}],
                    }
                ],
            },
        ]
    )

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
    ) == "done"

    assert len(payloads) == 2
    first_env_text = payloads[0]["input"][0]["content"][0]["text"]
    second_env_text = payloads[1]["input"][0]["content"][0]["text"]
    assert first_env_text.startswith("[Agent Environment Context]\n")
    assert second_env_text.startswith("[Agent Environment Context]\n")
    assert "2026-06-30T09:00:00+08:00" in first_env_text
    assert "2026-06-30T09:00:01+08:00" in second_env_text
    assert "run echo" in json.dumps(payloads[1]["input"], ensure_ascii=False)
    assert all("[Agent Environment Context]" not in str(message.get("content")) for message in agent.messages)

    summaries = _runtime_notice_payloads(agent.events, "openai_responses_request_summary")
    assert summaries[-1]["environment_context_chars"] > 0


def test_explicit_context_continuation_preserves_assistant_content_with_function_call():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesContinuationMode": "explicit_context",
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []
    order = []
    agent._aitools_persist_assistant_tool_call_note = lambda message: order.append(
        ("persist", message.get("content"))
    )

    def echo_tool(message=None):
        order.append(("tool", message))
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool

    responses = iter(
        [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "I will inspect the first result."}],
                    },
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "echo_tool",
                        "arguments": '{"message":"hello"}',
                        "status": "completed",
                    },
                ],
            },
            {
                "id": "resp-final",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "done"}],
                    }
                ],
            },
        ]
    )

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
    ) == "done"

    assistant_messages = [message for message in agent.messages if message.get("role") == "assistant"]
    assert assistant_messages[0]["content"] == "I will inspect the first result."
    assert order == [
        ("persist", "I will inspect the first result."),
        ("tool", "hello"),
    ]
    continuation_text = json.dumps(payloads[1]["input"], ensure_ascii=False)
    assert continuation_text.count("I will inspect the first result.") == 1
    preserved = [
        item
        for item in payloads[1]["input"]
        if item.get("type") == "message"
        and item.get("role") == "assistant"
        and item.get("content") == [{"type": "output_text", "text": "I will inspect the first result."}]
    ]
    assert len(preserved) == 1
    assert any(item.get("type") == "function_call" and item.get("call_id") == "call-1" for item in payloads[1]["input"])
    assert any(item.get("type") == "function_call_output" and item.get("call_id") == "call-1" for item in payloads[1]["input"])

