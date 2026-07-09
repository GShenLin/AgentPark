import pytest
from types import SimpleNamespace


def _build_agent():
    from src.providers.claude_agent import ClaudeAgent

    agent = ClaudeAgent.__new__(ClaudeAgent)
    agent.provider_name = "fable-5-krill"
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://api.anthropic.com/v1",
        "model": "claude-fable-5",
        "toolResultSubmissionMaxChars": 50000,
    }
    agent.messages = [{"role": "user", "content": "hello"}]
    agent.system_prompt = None
    agent.internal_memory_enabled = False
    agent.tools = SimpleNamespace(tool_declarations=[], function_map={})
    agent.tool_event_callback = None
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    return agent


def test_claude_agent_uses_native_messages_payload_without_responses_fields():
    agent = _build_agent()
    captured = {}

    def fake_send(payload, **_kwargs):
        captured.update(payload)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    agent.send_messages = fake_send

    assert agent.Send(reasoning_effort="", web_search="disabled", thinking="disabled") == "ok"

    assert captured["model"] == "claude-fable-5"
    assert captured["max_tokens"] == 4096
    assert captured["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
    assert "input" not in captured
    assert "reasoning" not in captured
    assert "include" not in captured


def test_claude_agent_emits_provider_request_summary_for_messages_api():
    import json

    from src.providers.curl_transport import CurlResponse

    agent = _build_agent()
    agent.messages = [
        {"role": "system", "content": "<environment_context>env</environment_context>"},
        {"role": "user", "content": "hello"},
    ]
    events = []
    captured = {}
    agent.tool_event_callback = events.append

    def fake_curl_post_once_raw(**kwargs):
        captured["payload"] = json.loads(kwargs["payload_json"])
        return CurlResponse(
            body=json.dumps({"content": [{"type": "text", "text": "ok"}]}, ensure_ascii=False),
            status_code=200,
        )

    agent._curl_post_once_raw = fake_curl_post_once_raw

    assert agent.Send(web_search="enabled", thinking="disabled", reasoning_effort="") == "ok"

    summaries = [
        json.loads(event["message"])
        for event in events
        if event.get("type") == "runtime_notice" and event.get("stage") == "provider_request_summary"
    ]
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["request_api"] == "claude_messages"
    assert summary["input_item_count"] == 2
    assert summary["environment_context_chars"] > 0
    assert summary["tools_included"] == ["web_search"]
    assert summary["stream"] is False
    assert captured["payload"]["tools"] == [{"type": "web_search_20260318", "name": "web_search"}]


def test_claude_agent_maps_reasoning_effort_to_output_config():
    agent = _build_agent()
    captured = {}

    def fake_send(payload, **_kwargs):
        captured.update(payload)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    agent.send_messages = fake_send

    assert agent.Send(reasoning_effort="high") == "ok"

    assert captured["output_config"] == {"effort": "high"}
    assert "reasoning_effort" not in captured


def test_claude_agent_uses_config_reasoning_effort_when_node_value_empty():
    agent = _build_agent()
    agent.config["reasoningEffort"] = "high"
    captured = {}

    def fake_send(payload, **_kwargs):
        captured.update(payload)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    agent.send_messages = fake_send

    assert agent.Send(reasoning_effort="") == "ok"

    assert captured["output_config"] == {"effort": "high"}


def test_claude_agent_moves_system_messages_to_top_level_system():
    agent = _build_agent()
    agent.messages = [
        {"role": "system", "content": "Node system prompt."},
        {"role": "user", "content": "old user"},
        {"role": "assistant", "content": "old answer"},
        {"role": "system", "content": "Injected skill instructions."},
        {"role": "user", "content": "current user"},
    ]
    captured = {}

    def fake_send(payload, **_kwargs):
        captured.update(payload)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    agent.send_messages = fake_send

    assert agent.Send() == "ok"

    assert captured["system"] == "Node system prompt.\n\nInjected skill instructions."
    assert captured["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "old user"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "old answer"}]},
        {"role": "user", "content": [{"type": "text", "text": "current user"}]},
    ]


def test_claude_agent_supports_native_web_search_and_thinking():
    agent = _build_agent()
    captured = {}

    def fake_send(payload, **_kwargs):
        captured.update(payload)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    agent.send_messages = fake_send

    assert agent.Send(web_search="enabled", thinking="enabled", reasoning_effort="") == "ok"

    assert captured["tools"] == [{"type": "web_search_20260318", "name": "web_search"}]
    assert captured["thinking"] == {"type": "enabled", "budget_tokens": 1024}


def test_claude_agent_maps_xhigh_and_max_reasoning_effort():
    agent = _build_agent()
    captured = {}

    def fake_send(payload, **_kwargs):
        captured.update(payload)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    agent.send_messages = fake_send

    assert agent.Send(reasoning_effort="xhigh") == "ok"
    assert captured["output_config"] == {"effort": "xhigh"}

    captured.clear()
    assert agent.Send(reasoning_effort="max") == "ok"
    assert captured["output_config"] == {"effort": "max"}


def test_claude_agent_rejects_unknown_reasoning_effort():
    agent = _build_agent()

    with pytest.raises(ValueError, match="output_config.effort"):
        agent.Send(reasoning_effort="auto")


def test_claude_agent_preserves_native_content_blocks_for_tool_followup():
    agent = _build_agent()
    tool_calls = [
        {
            "id": "toolu_1",
            "type": "function",
            "function": {"name": "read_file", "arguments": "{\"file_path\":\"README.md\"}"},
        }
    ]
    native_blocks = [
        {"type": "thinking", "thinking": "Need file.", "signature": "sig"},
        {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"file_path": "README.md"}},
    ]

    agent.messages = [
        {"role": "assistant", "content": "", "tool_calls": tool_calls, "_claude_content_blocks": native_blocks},
        {"role": "tool", "tool_call_id": "toolu_1", "name": "read_file", "content": "ok"},
        {"role": "user", "content": "continue"},
    ]
    captured = {}

    def fake_send(payload, **_kwargs):
        captured.update(payload)
        return {"choices": [{"message": {"role": "assistant", "content": "done"}}]}

    agent.send_messages = fake_send

    assert agent.Send() == "done"

    assert captured["messages"][0] == {"role": "assistant", "content": native_blocks}
    assert captured["messages"][1] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}],
    }


def test_claude_agent_converts_openai_tools_to_claude_tool_declarations():
    agent = _build_agent()
    captured = {}

    def fake_send(payload, **_kwargs):
        captured.update(payload)
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    agent.send_messages = fake_send

    assert agent.Send(
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {"file_path": {"type": "string"}},
                        "required": ["file_path"],
                    },
                },
            }
        ]
    ) == "ok"

    assert captured["tools"] == [
        {
            "name": "read_file",
            "description": "Read a file.",
            "input_schema": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"],
            },
        }
    ]


def test_claude_agent_rejects_malformed_tools_before_provider_request():
    agent = _build_agent()
    called = False

    def fake_send(_payload, **_kwargs):
        nonlocal called
        called = True
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    agent.send_messages = fake_send

    with pytest.raises(ValueError, match="function.parameters"):
        agent.Send(tools=[{"type": "function", "function": {"name": "read_file"}}])

    assert called is False


def test_claude_agent_true_streaming_emits_deltas_and_final_text_once():
    agent = _build_agent()
    captured_payload = {}
    emitted = []

    def fake_send(payload, *, stream=False, stream_handler=None, thinking_stream_handler=None):
        _ = thinking_stream_handler
        captured_payload.update(payload)
        assert stream is True
        assert callable(stream_handler)
        # Simulate the SSE loop already having emitted incremental deltas
        # while the request was in flight (mirrors ClaudeStreamRuntime).
        stream_handler("Hel", "Hel")
        stream_handler("lo", "Hello")
        return {"choices": [{"message": {"role": "assistant", "content": "Hello"}}]}

    agent.send_messages = fake_send

    result = agent.Send(stream=True, stream_handler=lambda delta, full: emitted.append((delta, full)))

    assert result == "Hello"
    # The final non-tool-call text branch must NOT re-emit the full text a
    # second time when the turn was already streamed -- only the two SSE
    # deltas simulated above should have reached the handler.
    assert emitted == [("Hel", "Hel"), ("lo", "Hello")]


def test_claude_agent_tool_call_preamble_emitted_once_when_not_streaming():
    agent = _build_agent()
    emitted = []

    def fake_send(_payload, **_kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Let me check that file first.",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "read_file", "arguments": "{}"},
                            }
                        ],
                    }
                }
            ]
        }

    agent.send_messages = fake_send
    agent.extract_tool_calls = lambda message: (message or {}).get("tool_calls") or []
    agent.pick_response_message = lambda choices, run_tools: (choices[0]["message"], 0)
    agent.execute_tool_calls_parallel = lambda tool_calls: []
    agent._build_non_retryable_tool_warning = lambda *a, **k: ""

    result = agent.Send(
        run_tools=False,
        stream=False,
        stream_handler=lambda delta, full: emitted.append((delta, full)),
    )

    assert result["type"] == "function_call"
    assert emitted == [("Let me check that file first.", "Let me check that file first.")]
