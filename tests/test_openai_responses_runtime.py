import json

from src.tool.base_tool import BaseTool
from src.tool.tool_call_protocol import ToolCallExecution


def _runtime_notice_payloads(events, stage):
    return [
        json.loads(event["message"])
        for event in events
        if event.get("type") == "runtime_notice" and event.get("stage") == stage
    ]


def test_openai_send_uses_responses_endpoint_when_responses_api_enabled():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test-key",
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
    agent.provider_name = "openai"
    agent.system_prompt = None
    agent.messages = [{"role": "user", "content": "hello"}]
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.tool_declarations = []
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
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

    result = agent.Send(web_search="disabled", thinking="disabled", reasoning_effort="", stream=False)

    assert result == "responses ok"
    assert requests[0]["endpoint"] == "responses"
    assert requests[0]["url"] == "https://api.openai.test/v1/responses"
    payload = json.loads(requests[0]["payload_json"])
    assert payload["input"][-1] == {
        "type": "message",
        "role": "user",
        "status": "completed",
        "content": [{"type": "input_text", "text": "hello"}],
    }
    assert "messages" not in payload


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


def test_responses_input_preserves_developer_messages():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {}
    agent.provider_name = "openai"

    payload = agent._build_responses_input(
        [
            {"role": "developer", "content": "<collaboration_mode>\nPlan\n</collaboration_mode>"},
            {"role": "user", "content": "hello"},
        ]
    )

    assert payload[0]["type"] == "message"
    assert payload[0]["role"] == "developer"
    assert payload[0]["content"] == [
        {"type": "input_text", "text": "<collaboration_mode>\nPlan\n</collaboration_mode>"}
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
    assert payloads[0]["tool_choice"] == "auto"
    assert payloads[0]["parallel_tool_calls"] is True


def test_openai_responses_payload_includes_codex_like_tool_and_reasoning_fields():
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
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    payloads = []

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "run"}],
        active_tools=[
            {
                "type": "function",
                "function": {
                    "name": "echo_tool",
                    "description": "Echo text.",
                    "parameters": {"type": "object"},
                },
            }
        ],
        run_tools=False,
        reasoning_effort="medium",
    )

    assert out == "ok"
    assert payloads[0]["tool_choice"] == "auto"
    assert payloads[0]["parallel_tool_calls"] is True
    assert payloads[0]["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert payloads[0]["include"] == ["reasoning.encrypted_content"]


def test_openai_responses_payload_uses_config_reasoning_summary():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "reasoningSummary": "detailed",
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.system_prompt = None
    agent.messages = [{"role": "user", "content": "hello"}]
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

    out = agent.Send(run_tools=False, reasoning_effort="medium")

    assert out == "ok"
    assert payloads[0]["reasoning"] == {"effort": "medium", "summary": "detailed"}


def test_openai_responses_payload_disables_reasoning_summary():
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
        messages=[{"role": "user", "content": "hello"}],
        active_tools=[],
        run_tools=False,
        reasoning_effort="medium",
        reasoning_summary="disabled",
    )

    assert out == "ok"
    assert payloads[0]["reasoning"] == {"effort": "medium"}


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


def test_openai_responses_reasoning_replay_policy_rejects_snake_case_key():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
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
    assert any(
        item.get("type") == "message"
        and item.get("role") == "user"
        and item.get("content")
        and item["content"][0].get("text", "").startswith("<environment_context>")
        for item in payloads[1]["input"]
        if isinstance(item, dict)
    )
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
    assert len(feedback_input) == 3
    assert feedback_input[0]["role"] == "developer"
    assert feedback_input[0]["content"][0]["text"].startswith("<permissions instructions>")
    assert feedback_input[1]["role"] == "user"
    assert feedback_input[1]["content"][0]["text"].startswith("<environment_context>")
    feedback_text = feedback_input[2]["content"][0]["text"]
    assert len(json.dumps(feedback_input, ensure_ascii=False)) < 10000
    assert "inspect DA_Action_Book" in feedback_text
    assert "tool_result_submission_error" in feedback_text
    assert "asset-row-" not in feedback_text
    feedback_payload = json.loads(feedback_text.split("\n", 1)[1])
    diagnostics = feedback_payload["diagnostics"]
    assert diagnostics["likely_cause"] == "compacted_large_tool_result_context"
    assert diagnostics["largest_tool_result_chars"] > 0
    assert diagnostics["provider_request"]["input_item_count"] == 5
    request_summaries = _runtime_notice_payloads(agent.events, "provider_request_summary")
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
            "workspace_path": str(tmp_path),
            "working_path": str(tmp_path / "work"),
            "shell": "powershell",
            "current_date": "2026-06-30",
            "timezone": "Asia/Shanghai",
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
    first_permissions_text = payloads[0]["input"][0]["content"][0]["text"]
    first_env_text = payloads[0]["input"][1]["content"][0]["text"]
    second_permissions_text = payloads[1]["input"][0]["content"][0]["text"]
    second_env_text = payloads[1]["input"][1]["content"][0]["text"]
    assert payloads[0]["input"][0]["role"] == "developer"
    assert first_permissions_text.startswith("<permissions instructions>")
    assert second_permissions_text.startswith("<permissions instructions>")
    assert payloads[0]["input"][1]["role"] == "user"
    assert first_env_text.startswith("<environment_context>")
    assert second_env_text.startswith("<environment_context>")
    assert "<current_date>2026-06-30</current_date>" in first_env_text
    assert "<timezone>Asia/Shanghai</timezone>" in first_env_text
    assert "2026-06-30T09:00:00+08:00" not in first_env_text
    assert "2026-06-30T09:00:01+08:00" not in second_env_text
    assert "working_path" not in first_env_text
    assert str(tmp_path / "work") not in first_env_text
    assert "run echo" in json.dumps(payloads[1]["input"], ensure_ascii=False)
    assert all("<environment_context>" not in str(message.get("content")) for message in agent.messages)
    assert all("<permissions instructions>" not in str(message.get("content")) for message in agent.messages)
    assert all("[Agent Turn Context]" not in str(message.get("content")) for message in agent.messages)

    summaries = _runtime_notice_payloads(agent.events, "provider_request_summary")
    assert summaries[-1]["request_api"] == "responses"
    assert summaries[-1]["environment_context_chars"] > 0
    assert summaries[-1]["permissions_context_chars"] > 0
    assert summaries[0]["turn_context_chars"] == 0
    assert summaries[1]["turn_context_chars"] == 0
    assert summaries[0]["context_update_mode"] == "full"
    assert summaries[1]["context_update_mode"] == "unchanged"
    assert summaries[0]["context_item_hash"] == summaries[1]["context_item_hash"]
    context_updates = _runtime_notice_payloads(agent.events, "openai_responses_context_update")
    assert [item["context_update_mode"] for item in context_updates] == ["full", "unchanged"]
    assert "volatile" not in context_updates[0]["context_item"]


def test_responses_turn_context_persists_reference_between_sends(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from src.providers.openai_agent import OpenAIAgent
    import src.providers.agent_environment_context as environment_context

    def fake_context(agent, *, current_input=None):
        _ = agent, current_input
        return {
            "workspace_path": str(tmp_path),
            "shell": "powershell",
            "request_time": "2026-07-02T10:00:00+08:00",
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
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "memory.md"))
    agent._agentpark_workspace_root = str(tmp_path)
    payloads = []
    responses = iter(
        [
            {"id": "resp-1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "one"}]}]},
            {"id": "resp-2", "output": [{"type": "message", "content": [{"type": "output_text", "text": "two"}]}]},
        ]
    )

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(messages=[{"role": "user", "content": "first"}], active_tools=[], run_tools=True) == "one"
    agent.events.clear()
    assert agent._send_via_responses(messages=[{"role": "user", "content": "second"}], active_tools=[], run_tools=True) == "two"

    assert (tmp_path / "agent_turn_context.json").is_file()
    assert (tmp_path / "agent_context_history.json").is_file()
    second_updates = _runtime_notice_payloads(agent.events, "openai_responses_context_update")
    assert second_updates[0]["context_update_mode"] == "unchanged"
    assert second_updates[0]["model_context_update_mode"] == "full"
    assert second_updates[0]["persistent_context_update_mode"] == "unchanged"
    assert payloads[1]["input"][0]["role"] == "developer"
    assert payloads[1]["input"][1]["role"] == "user"
    assert payloads[1]["input"][1]["content"][0]["text"].startswith("<environment_context>")
    assert all("[Agent Turn Context]" not in json.dumps(payload.get("input"), ensure_ascii=False) for payload in payloads)


def test_responses_context_history_replaces_stale_context_on_change(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from src.providers.openai_agent import OpenAIAgent
    import src.providers.agent_environment_context as environment_context

    workspace = {"path": str(tmp_path / "first")}

    def fake_context(agent, *, current_input=None):
        _ = agent, current_input
        return {
            "workspace_path": workspace["path"],
            "shell": "powershell",
            "request_time": "2026-07-02T10:00:00+08:00",
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
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "memory.md"))
    payloads = []
    responses = iter(
        [
            {"id": "resp-1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "one"}]}]},
            {"id": "resp-2", "output": [{"type": "message", "content": [{"type": "output_text", "text": "two"}]}]},
        ]
    )

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(messages=[{"role": "user", "content": "first"}], active_tools=[], run_tools=True) == "one"
    workspace["path"] = str(tmp_path / "second")
    agent.events.clear()
    assert agent._send_via_responses(messages=[{"role": "user", "content": "second"}], active_tools=[], run_tools=True) == "two"

    environment_items = [
        item
        for item in payloads[1]["input"]
        if item.get("type") == "message"
        and item.get("role") == "user"
        and item.get("content")
        and str(item["content"][0].get("text") or "").startswith("<environment_context>")
    ]
    assert len(environment_items) == 1
    environment_text = environment_items[0]["content"][0]["text"]
    assert "second" in environment_text
    assert "first" not in environment_text
    second_updates = _runtime_notice_payloads(agent.events, "openai_responses_context_update")
    assert second_updates[0]["context_update_mode"] == "diff"
    assert second_updates[0]["persistent_context_update_mode"] == "diff"


def test_responses_context_history_does_not_duplicate_tool_followup_context(tmp_path):
    from types import SimpleNamespace

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
    agent.provider_name = "openai"
    agent.messages = []
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "memory.md"))
    agent._agentpark_workspace_root = str(tmp_path)
    agent._execute_tool_call_envelopes_parallel = lambda _calls: [
        ToolCallExecution(
            func_name="echo_tool",
            call_id="call-1",
            cleaned_result='{"status":"success","text":"hello"}',
            image_data=None,
        )
    ]
    payloads = []
    first_responses = iter(
        [
            {"id": "resp-1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "one"}]}]},
        ]
    )

    def fake_first_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return next(first_responses)

    agent._post_json_with_retry = fake_first_post
    agent._stream_responses_with_retry = fake_first_post

    assert agent._send_via_responses(messages=[{"role": "user", "content": "first"}], active_tools=[], run_tools=True) == "one"

    second_responses = iter(
        [
            {
                "id": "resp-tool",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "echo_tool",
                        "arguments": "{}",
                        "status": "completed",
                    }
                ],
            },
            {"id": "resp-final", "output": [{"type": "message", "content": [{"type": "output_text", "text": "two"}]}]},
        ]
    )

    def fake_second_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return next(second_responses)

    agent._post_json_with_retry = fake_second_post
    agent._stream_responses_with_retry = fake_second_post

    assert agent._send_via_responses(messages=[{"role": "user", "content": "second"}], active_tools=[], run_tools=True) == "two"

    tool_followup_input = payloads[-1]["input"]

    def context_count(prefix):
        return sum(
            1
            for item in tool_followup_input
            if item.get("type") == "message"
            and item.get("content")
            and str(item["content"][0].get("text") or "").startswith(prefix)
        )

    assert context_count("<permissions instructions>") == 1
    assert context_count("<environment_context>") == 1
    assert context_count("# AGENTS.md instructions") <= 1


def test_responses_dedupes_persisted_runtime_context_history(tmp_path):
    from types import SimpleNamespace

    from src.providers.agent_context_history import save_agent_context_history
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
    agent.provider_name = "openai"
    agent.messages = []
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "memory.md"))
    agent._agentpark_workspace_root = str(tmp_path)
    context_item = {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "<environment_context>\n  <cwd>C:\\Project</cwd>\n</environment_context>"}],
        "status": "completed",
    }
    save_agent_context_history(agent, [context_item, dict(context_item)])
    payloads = []

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return {"id": "resp-1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(messages=[{"role": "user", "content": "hello"}], active_tools=[], run_tools=True) == "ok"

    environment_count = sum(
        1
        for item in payloads[0]["input"]
        if item.get("type") == "message"
        and item.get("content")
        and str(item["content"][0].get("text") or "").startswith("<environment_context>")
    )
    assert environment_count == 1
    saved_history = json.loads((tmp_path / "agent_context_history.json").read_text(encoding="utf-8"))
    assert len(saved_history["items"]) == 2


def test_responses_merges_developer_context_after_persisted_runtime_user_context(tmp_path):
    from types import SimpleNamespace

    from src.providers.agent_context_history import save_agent_context_history
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
    agent.provider_name = "openai"
    agent.messages = []
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "memory.md"))
    agent._agentpark_workspace_root = str(tmp_path)
    save_agent_context_history(
        agent,
        [
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "<permissions instructions>\nExisting.\n</permissions instructions>"}],
                "status": "completed",
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "<environment_context>\n  <cwd>C:\\Project</cwd>\n</environment_context>"}],
                "status": "completed",
            },
        ],
    )
    payloads = []

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return {"id": "resp-1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(
        messages=[
            {"role": "system", "content": "Base instructions."},
            {"role": "developer", "content": "Operational memory for this node:\n- Use current evidence."},
            {"role": "user", "content": "hello"},
        ],
        active_tools=[],
        run_tools=True,
    ) == "ok"

    first = payloads[0]["input"][0]
    assert first["role"] == "developer"
    first_texts = [part["text"] for part in first["content"]]
    assert first_texts[0].startswith("<permissions instructions>")
    assert any(text.startswith("Operational memory for this node:") for text in first_texts)
    assert all(
        not (
            item.get("role") == "developer"
            and item.get("content")
            and item["content"][0].get("text", "").startswith("Operational memory for this node:")
        )
        for item in payloads[0]["input"][1:]
    )


def test_responses_context_history_strips_operational_memory_from_persisted_developer_context(tmp_path):
    from types import SimpleNamespace

    from src.providers.agent_context_history import save_agent_context_history
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
    agent.provider_name = "openai"
    agent.messages = []
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "memory.md"))
    agent._agentpark_workspace_root = str(tmp_path)
    save_agent_context_history(
        agent,
        [
            {
                "type": "message",
                "role": "developer",
                "content": [
                    {"type": "input_text", "text": "<permissions instructions>\nExisting.\n</permissions instructions>"},
                    {"type": "input_text", "text": "Operational memory for this node:\n- stale memory."},
                ],
                "status": "completed",
            }
        ],
    )
    payloads = []

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return {"id": "resp-1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(
        messages=[
            {"role": "developer", "content": "Operational memory for this node:\n- fresh memory."},
            {"role": "user", "content": "hello"},
        ],
        active_tools=[],
        run_tools=True,
    ) == "ok"

    developer_texts = [part["text"] for part in payloads[0]["input"][0]["content"]]
    operational_texts = [text for text in developer_texts if text.startswith("Operational memory for this node:")]
    assert operational_texts == ["Operational memory for this node:\n- fresh memory."]
    saved_history = json.loads((tmp_path / "agent_context_history.json").read_text(encoding="utf-8"))
    assert "Operational memory for this node:" not in json.dumps(saved_history, ensure_ascii=False)


def test_responses_plan_collaboration_mode_injects_developer_context(tmp_path):
    from types import SimpleNamespace

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
    agent.provider_name = "openai"
    agent.messages = []
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "memory.md"))
    agent._agentpark_collaboration_mode = "plan"
    payloads = []

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return {"id": "resp-1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(messages=[{"role": "user", "content": "plan it"}], active_tools=[], run_tools=True) == "ok"

    assert payloads[0]["input"][0]["role"] == "developer"
    assert payloads[0]["input"][0]["content"][0]["text"].startswith("<permissions instructions>")
    assert payloads[0]["input"][0]["content"][1]["text"].startswith("<collaboration_mode>")
    assert payloads[0]["input"][1]["role"] == "user"
    assert payloads[0]["input"][1]["content"][0]["text"].startswith("<environment_context>")
    developer_item = payloads[0]["input"][0]
    developer_text = developer_item["content"][1]["text"]
    assert developer_text.startswith("<collaboration_mode>\n")
    assert "You are in Plan Mode" in developer_text
    assert "<proposed_plan>" in developer_text
    summaries = _runtime_notice_payloads(agent.events, "provider_request_summary")
    assert summaries[0]["permissions_context_chars"] > 0
    assert summaries[0]["collaboration_context_chars"] > 0
    assert summaries[0]["input_items"][0]["context_kind"] == "runtime_context"
    assert summaries[0]["input_items"][0]["context_kinds"] == ["permissions", "collaboration_mode"]
    context_updates = _runtime_notice_payloads(agent.events, "openai_responses_context_update")
    assert context_updates[0]["context_item"]["collaboration_mode"] == {"mode": "plan"}


def test_responses_writes_sanitized_request_payload_log(tmp_path):
    from types import SimpleNamespace

    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "secret-key",
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
    agent.provider_name = "openai"
    agent.messages = []
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "memory.md"))
    agent._agentpark_workspace_root = str(tmp_path)

    def fake_post(**kwargs):
        return {"id": "resp-1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(messages=[{"role": "user", "content": "log me"}], active_tools=[], run_tools=True) == "ok"

    payload_log = tmp_path / "responses_payloads.jsonl"
    assert payload_log.is_file()
    records = [json.loads(line) for line in payload_log.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1
    record = records[0]
    assert record["stage"] == "openai_responses_request_payload"
    assert record["payload"]["model"] == "gpt-test"
    assert "apiKey" not in json.dumps(record["payload"], ensure_ascii=False)
    assert record["payload"]["input"][0]["role"] == "developer"
    assert record["payload"]["input"][1]["role"] == "user"
    assert record["payload"]["input"][2]["content"][0]["text"] == "log me"
    assert record["request_summary"]["input_item_count"] == 3

    summaries = _runtime_notice_payloads(agent.events, "provider_request_summary")
    assert summaries[0]["payload_log_path"] == str(payload_log)
    payload_log_events = _runtime_notice_payloads(agent.events, "openai_responses_request_payload_log")
    assert payload_log_events[0]["path"] == str(payload_log)


def test_responses_sends_instruction_parameter_and_preserves_system_prompt(tmp_path):
    from types import SimpleNamespace

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
    agent.provider_name = "openai"
    agent.messages = []
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "memory.md"))
    agent._agentpark_workspace_root = str(tmp_path)
    agent._agentpark_responses_instruction = "Use the Responses instructions parameter."
    payloads = []

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return {"id": "resp-1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(
        messages=[
            {"role": "system", "content": "You are the node system prompt."},
            {"role": "user", "content": "hello"},
        ],
        active_tools=[],
        run_tools=True,
    ) == "ok"

    assert payloads[0]["instructions"] == "Use the Responses instructions parameter."
    system_item = next(item for item in payloads[0]["input"] if item.get("role") == "system")
    assert system_item["content"][0]["text"] == "You are the node system prompt."
    assert payloads[0]["input"][-1]["role"] == "user"
    assert payloads[0]["input"][-1]["content"][0]["text"] == "hello"
    summaries = _runtime_notice_payloads(agent.events, "provider_request_summary")
    assert summaries[0]["instructions_present"] is True
    assert summaries[0]["instructions_chars"] == len("Use the Responses instructions parameter.")


def test_responses_stream_sends_instruction_parameter_and_system_input(tmp_path):
    from types import SimpleNamespace

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
    agent.provider_name = "openai"
    agent.messages = []
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "memory.md"))
    agent._agentpark_workspace_root = str(tmp_path)
    agent._agentpark_responses_instruction = "Stream through payload.instructions."
    payloads = []
    stream_events = []

    def fake_stream(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        handler = kwargs.get("stream_handler")
        if callable(handler):
            handler("O", "O")
            handler("K", "OK")
        return {"id": "resp-stream", "output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}]}

    agent._post_json_with_retry = fake_stream
    agent._stream_responses_with_retry = fake_stream

    assert agent._send_via_responses(
        messages=[
            {"role": "system", "content": "System stream prompt."},
            {"role": "user", "content": "hello"},
        ],
        active_tools=[],
        run_tools=True,
        stream_handler=lambda delta, full: stream_events.append((delta, full)),
    ) == "OK"

    assert stream_events == [("O", "O"), ("K", "OK")]
    assert payloads[0]["stream"] is True
    assert payloads[0]["instructions"] == "Stream through payload.instructions."
    system_item = next(item for item in payloads[0]["input"] if item.get("role") == "system")
    assert system_item["content"][0]["text"] == "System stream prompt."


def test_responses_reuses_instructions_for_explicit_context_tool_followups(tmp_path):
    from types import SimpleNamespace

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
    agent.provider_name = "openai"
    agent.messages = []
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "memory.md"))
    agent._agentpark_workspace_root = str(tmp_path)
    agent._agentpark_responses_instruction = "Use the Responses instructions parameter."
    agent._execute_tool_call_envelopes_parallel = lambda _calls: [
        ToolCallExecution(
            func_name="echo_tool",
            call_id="call-1",
            cleaned_result='{"status":"success","text":"hello"}',
            image_data=None,
        )
    ]
    payloads = []
    responses = iter(
        [
            {
                "id": "resp-tool",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "echo_tool",
                        "arguments": "{}",
                        "status": "completed",
                    }
                ],
            },
            {"id": "resp-final", "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]},
        ]
    )

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(
        messages=[
            {"role": "system", "content": "You are the node system prompt."},
            {"role": "user", "content": "run echo"},
        ],
        active_tools=[],
        run_tools=True,
    ) == "ok"

    assert len(payloads) == 2
    assert payloads[0]["instructions"] == "Use the Responses instructions parameter."
    assert payloads[1]["instructions"] == "Use the Responses instructions parameter."
    assert any(item.get("role") == "system" for payload in payloads for item in payload["input"])
    summaries = _runtime_notice_payloads(agent.events, "provider_request_summary")
    assert [summary["instructions_present"] for summary in summaries] == [True, True]


def test_responses_merges_initial_developer_context_before_user_context(tmp_path):
    from types import SimpleNamespace

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
    agent.provider_name = "openai"
    agent.messages = []
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "memory.md"))
    agent._agentpark_workspace_root = str(tmp_path)
    agent._agentpark_responses_instruction = "Base instructions."
    payloads = []

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return {"id": "resp-1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(
        messages=[
            {"role": "system", "content": "System prompt."},
            {"role": "developer", "content": "Operational memory for this node:\n- Keep it short."},
            {"role": "user", "content": "hello"},
        ],
        active_tools=[],
        run_tools=True,
    ) == "ok"

    assert payloads[0]["instructions"] == "Base instructions."
    first = payloads[0]["input"][0]
    assert first["role"] == "developer"
    assert first["content"][0]["text"].startswith("<permissions instructions>")
    assert first["content"][1]["text"].startswith("Operational memory for this node:")
    assert any(item.get("role") == "system" for item in payloads[0]["input"])
    system_item = next(item for item in payloads[0]["input"] if item.get("role") == "system")
    assert system_item["content"][0]["text"] == "System prompt."
    assert any(item.get("role") == "user" and item["content"][0]["text"].startswith("<environment_context>") for item in payloads[0]["input"])
    assert all(item.get("role") != "developer" for item in payloads[0]["input"][1:])


def test_responses_injects_codex_like_agents_md_context(tmp_path):
    from types import SimpleNamespace

    from src.providers.openai_agent import OpenAIAgent

    (tmp_path / "AGENTS.md").write_text("Use rg before broad file scans.\n", encoding="utf-8")
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
    agent.provider_name = "openai"
    agent.messages = []
    agent.internal_memory_enabled = False
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "memory.md"))
    agent._agentpark_workspace_root = str(tmp_path)
    payloads = []

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return {"id": "resp-1", "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(messages=[{"role": "user", "content": "read instructions"}], active_tools=[], run_tools=True) == "ok"

    assert payloads[0]["input"][0]["role"] == "developer"
    contextual_user_item = payloads[0]["input"][1]
    assert contextual_user_item["role"] == "user"
    assert contextual_user_item["content"][0]["text"].startswith("<environment_context>")
    assert contextual_user_item["content"][1]["text"].startswith("# AGENTS.md instructions")
    assert "Use rg before broad file scans." in contextual_user_item["content"][1]["text"]

    summaries = _runtime_notice_payloads(agent.events, "provider_request_summary")
    assert summaries[0]["project_instructions_context_chars"] > 0
    assert summaries[0]["input_items"][1]["context_kinds"] == ["environment", "project_instructions"]
    context_updates = _runtime_notice_payloads(agent.events, "openai_responses_context_update")
    assert context_updates[0]["context_item"]["project_instructions"]["chars"] > 0


def test_explicit_context_continuation_preserves_assistant_content_with_function_call():
    from src.base_agent import BaseAgent
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
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.internal_memory_enabled = False
    agent.Message = BaseAgent.Message.__get__(agent, OpenAIAgent)
    payloads = []
    order = []
    agent._agentpark_persist_assistant_tool_call_note = lambda message: order.append(
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


def test_responses_tool_followup_appends_mid_turn_user_input():
    from src.providers.agent_runtime_context import AgentRuntimeContext, bind_agent_runtime_context
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
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    mid_turn_messages = [[{"role": "user", "content": "补充：不要继续查 A，改查 B。"}]]

    def consume_mid_turn_user_inputs():
        return mid_turn_messages.pop(0) if mid_turn_messages else []

    bind_agent_runtime_context(
        agent,
        AgentRuntimeContext(
            graph_id="g1",
            node_id="agent1",
            node_type_id="agent_node",
            consume_mid_turn_user_inputs=consume_mid_turn_user_inputs,
        ),
    )
    payloads = []
    responses = iter(
        [
            {
                "id": "resp-tool",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "echo_tool",
                        "arguments": "{}",
                        "status": "completed",
                    }
                ],
            },
            {"id": "resp-final", "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]},
        ]
    )

    def fake_post(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post
    agent._execute_tool_call_envelopes_parallel = lambda _calls: [
        ToolCallExecution(
            func_name="echo_tool",
            call_id="call-1",
            cleaned_result='{"status":"success"}',
            image_data=None,
        )
    ]

    assert agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=True,
    ) == "ok"

    assert len(payloads) == 2
    second_input = payloads[1]["input"]
    assert second_input[-2]["type"] == "function_call_output"
    assert second_input[-2]["call_id"] == "call-1"
    assert second_input[-1] == {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "补充：不要继续查 A，改查 B。"}],
        "status": "completed",
    }
    notices = _runtime_notice_payloads(agent.events, "openai_responses_mid_turn_user_input")
    assert notices == [{"message_count": 1, "input_item_count": 1}]

