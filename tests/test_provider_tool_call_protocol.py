import json
from types import SimpleNamespace

import pytest

from src.tool.base_tool import BaseTool
from src.providers.provider_errors import ProviderImageAttachmentError
from src.tool.tool_call_protocol import ToolCallExecution
from src.tool_context_compaction_trigger import ToolContextCompactionWindow


def _runtime_notice_payloads(events, stage):
    return [
        json.loads(event["message"])
        for event in events
        if event.get("type") == "runtime_notice" and event.get("stage") == stage
    ]


def _without_environment_context(items):
    def is_runtime_context(item):
        if not isinstance(item, dict) or item.get("type") != "message":
            return False
        content = item.get("content")
        if not isinstance(content, list) or not content:
            return False
        first = content[0]
        text = str(first.get("text") or "") if isinstance(first, dict) else ""
        return (
            text.startswith("<environment_context>")
            or text.startswith("<permissions instructions>")
        )

    return [
        item
        for item in items
        if not is_runtime_context(item)
    ]


def test_gemini_runtime_executes_function_call_via_tool_call_envelope():
    from src.providers.gemini_agent import GeminiAgent

    agent = GeminiAgent.__new__(GeminiAgent)
    agent.config = {}
    agent.provider_name = "gemini"
    agent.tools = BaseTool(agent)
    captured = []

    def echo_tool(message=None):
        captured.append(message)
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool

    results = agent._execute_function_calls_parallel(
        [{"name": "echo_tool", "args": {"message": "hello"}}]
    )

    assert captured == ["hello"]
    assert len(results) == 1
    assert isinstance(results[0], ToolCallExecution)
    assert results[0].func_name == "echo_tool"
    assert str(results[0].call_id).startswith("gemini-")
    assert results[0].cleaned_result == "echo:hello"
    assert results[0].status == "completed"
    assert results[0].error is None


def test_doubao_runtime_executes_tool_call_via_tool_call_envelope():
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {}
    agent.provider_name = "doubao"
    agent.tools = BaseTool(agent)
    captured = []

    def echo_tool(message=None):
        captured.append(message)
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool

    results = agent._execute_tool_calls_parallel(
        [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": "echo_tool", "arguments": '{"message":"hello"}'},
            }
        ]
    )

    assert captured == ["hello"]
    assert len(results) == 1
    assert isinstance(results[0], ToolCallExecution)
    assert results[0].func_name == "echo_tool"
    assert results[0].call_id == "call-1"
    assert results[0].cleaned_result == "echo:hello"
    assert results[0].status == "completed"
    assert results[0].error is None


def test_doubao_runtime_returns_invalid_arguments_tool_error():
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {}
    agent.provider_name = "doubao"
    agent.tools = BaseTool(agent)

    tool_calls = [
        {
            "id": "call-bad",
            "type": "function",
            "function": {
                "name": "apply_patch",
                "arguments": '{"patch":"*** Begin Patch\n*** End Patch"}',
            },
        }
    ]

    extracted = agent._extract_tool_calls({"tool_calls": tool_calls})
    results = agent._execute_tool_calls_parallel(extracted)

    assert len(results) == 1
    assert results[0].func_name == "apply_patch"
    assert results[0].call_id == "call-bad"
    assert results[0].status == "error"
    payload = json.loads(results[0].cleaned_result)
    assert payload["status"] == "invalid_arguments"
    assert payload["call_id"] == "call-bad"
    assert "failed to parse tool arguments JSON" in payload["error"]


def test_tool_call_execution_serializes_only_at_explicit_boundary():
    execution = ToolCallExecution(
        func_name="echo_tool",
        call_id="call-1",
        cleaned_result="echo:hello",
        image_data=None,
        status="completed",
        error=None,
        diagnostics=("diag",),
    )

    assert execution.to_dict() == {
        "func_name": "echo_tool",
        "call_id": "call-1",
        "cleaned_result": "echo:hello",
        "image_data": None,
        "status": "completed",
        "error": None,
        "diagnostics": ["diag"],
    }


def test_provider_parallel_tool_worker_error_returns_typed_execution():
    from src.providers.doubao_agent import DouBaoAgent
    from src.tool.tool_call_protocol import ToolCallEnvelope

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {}
    agent.provider_name = "doubao"
    agent.tools = BaseTool(agent)

    def broken_execute(_tool_call):
        raise RuntimeError("worker boom")

    agent.tools.execute_tool_call = broken_execute
    call = ToolCallEnvelope(
        name="broken_tool",
        call_id="call-broken",
        arguments={},
        arguments_json="{}",
        provider="unit",
    )

    results = agent._execute_tool_call_envelopes_parallel([call])

    assert len(results) == 1
    assert isinstance(results[0], ToolCallExecution)
    assert results[0].func_name == "broken_tool"
    assert results[0].call_id == "call-broken"
    assert results[0].status == "error"
    assert "worker boom" in results[0].error


def test_provider_parallel_tool_worker_requires_envelope_list():
    from src.providers.tool_call_execution import execute_tool_call_envelopes_parallel

    with pytest.raises(TypeError, match="ToolCallEnvelope"):
        execute_tool_call_envelopes_parallel(
            tool_calls=[{"name": "bad"}],
            execute_tool_call=lambda _call: None,
            execute_tasks_parallel_ordered=lambda **_kwargs: [],
        )


def test_provider_blocks_repeated_rg_tool_signature_before_execution():
    from src.providers.openai_agent import OpenAIAgent
    from src.tool.tool_call_protocol import ToolCallEnvelope

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {}
    agent.provider_name = "openai"
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.tools = BaseTool(agent)
    executed = []

    def fake_rg_search(**kwargs):
        executed.append(kwargs)
        return '{"status":"success","matches":[]}'

    agent.tools.function_map["rg_search_text"] = fake_rg_search
    agent._reset_tool_call_loop_guard()
    calls = [
        ToolCallEnvelope(
            name="rg_search_text",
            call_id="call-1",
            arguments={"query": "needle", "include_globs": ["src/**/*.py"], "max_results": 100},
            arguments_json='{"query":"needle","include_globs":["src/**/*.py"],"max_results":100}',
            provider="unit",
        ),
        ToolCallEnvelope(
            name="rg_search_text",
            call_id="call-2",
            arguments={"query": "needle", "include_globs": ["src/**/*.py"], "max_results": 100},
            arguments_json='{"query":"needle","include_globs":["src/**/*.py"],"max_results":100}',
            provider="unit",
        ),
    ]

    results = agent._execute_tool_call_envelopes_parallel(calls)

    assert len(executed) == 1
    assert results[0].status == "completed"
    assert results[1].status == "blocked"
    blocked_payload = json.loads(results[1].cleaned_result)
    assert blocked_payload["policy"] == "repeated_tool_signature_guard"
    assert blocked_payload["retryable"] is False
    assert blocked_payload["previous_call_id"] == "call-1"
    notices = [
        event
        for event in agent.events
        if event.get("type") == "runtime_notice" and event.get("stage") == "tool_call_loop_blocked"
    ]
    assert len(notices) == 1


def test_provider_blocks_rg_repeat_that_only_increases_max_results():
    from src.providers.openai_agent import OpenAIAgent
    from src.tool.tool_call_protocol import ToolCallEnvelope

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {}
    agent.provider_name = "openai"
    agent.tools = BaseTool(agent)
    executed = []
    agent.tools.function_map["rg_list_files"] = lambda **kwargs: executed.append(kwargs) or '{"status":"success"}'
    agent._reset_tool_call_loop_guard()

    results = agent._execute_tool_call_envelopes_parallel(
        [
            ToolCallEnvelope(
                name="rg_list_files",
                call_id="call-1",
                arguments={"include_globs": ["src/**/*.py"], "max_results": 100},
                arguments_json='{"include_globs":["src/**/*.py"],"max_results":100}',
                provider="unit",
            ),
            ToolCallEnvelope(
                name="rg_list_files",
                call_id="call-2",
                arguments={"include_globs": ["src/**/*.py"], "max_results": 1000},
                arguments_json='{"include_globs":["src/**/*.py"],"max_results":1000}',
                provider="unit",
            ),
        ]
    )

    assert len(executed) == 1
    assert results[1].status == "blocked"
    payload = json.loads(results[1].cleaned_result)
    assert "max_results" in payload["reason"]


def test_provider_openai_tool_call_items_preserve_parse_failures_in_order():
    from src.providers.tool_call_execution import execute_tool_call_items_parallel
    from src.providers.tool_call_execution import parse_openai_tool_call_items
    from src.tool.tool_call_protocol import ToolCallExecution

    items = parse_openai_tool_call_items(
        [
            {
                "id": "call-bad",
                "type": "function",
                "function": {
                    "name": "apply_patch",
                    "arguments": '{"patch":"*** Begin Patch\n*** End Patch"}',
                },
            },
            {
                "id": "call-ok",
                "type": "function",
                "function": {"name": "echo_tool", "arguments": '{"message":"hello"}'},
            },
        ],
        provider="unit",
    )

    executions = execute_tool_call_items_parallel(
        tool_call_items=items,
        execute_tool_call_envelopes=lambda calls: [
            ToolCallExecution(
                func_name=call.name,
                call_id=call.call_id,
                cleaned_result="ok",
            )
            for call in calls
        ],
    )

    assert [item.call_id for item in executions] == ["call-bad", "call-ok"]
    assert executions[0].status == "error"
    assert json.loads(executions[0].cleaned_result)["status"] == "invalid_arguments"
    assert executions[1].status == "completed"


def test_doubao_responses_runtime_uses_envelopes_for_tool_continuation():
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://example.test/v1",
        "model": "doubao-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "doubao"
    agent.messages = []
    agent.tools = BaseTool(agent)
    requests = []
    captured = []

    def echo_tool(message=None):
        captured.append(message)
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )

    responses = iter(
        [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "echo_tool",
                        "arguments": '{"message":"hello"}',
                    }
                ],
            },
            {
                "id": "resp-2",
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
        requests.append(kwargs)
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=True,
        thinking_mode="disabled",
        web_search_mode="disabled",
    )

    assert out == "done"
    assert captured == ["hello"]
    assert len(requests) == 2
    second_payload = requests[1]["payload_json"]
    assert '"type": "function_call_output"' in second_payload
    assert '"call_id": "call-1"' in second_payload
    assert '"status": "completed"' in second_payload
    assert '"previous_response_id"' not in second_payload


def test_doubao_responses_invalid_tool_arguments_return_tool_error_and_continue():
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://example.test/v1",
        "model": "doubao-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "doubao"
    agent.messages = []
    agent.tools = BaseTool(agent)
    requests = []
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )

    responses = iter(
        [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call-bad",
                        "name": "echo_tool",
                        "arguments": '{"message":',
                    }
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
        requests.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    assert agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=True,
        thinking_mode="disabled",
        web_search_mode="disabled",
    ) == "fixed"

    tool_message = agent.messages[1]
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == "call-bad"
    tool_payload = json.loads(tool_message["content"])
    assert tool_payload["status"] == "invalid_arguments"
    assert "failed to parse tool arguments JSON" in tool_payload["error"]
    continuation_input = _without_environment_context(requests[1]["input"])
    tool_output = next(item for item in continuation_input if item.get("type") == "function_call_output")
    assert tool_output["status"] == "completed"
    output_payload = json.loads(tool_output["output"])
    assert output_payload["status"] == "invalid_arguments"


def test_doubao_responses_compacts_oversized_tool_output_before_continuation():
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://example.test/v1",
        "model": "doubao-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 1000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "doubao"
    agent.messages = []
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.tools = BaseTool(agent)
    requests = []

    def huge_tool():
        return "x" * 5000

    agent.tools.function_map["huge_tool"] = huge_tool
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )

    responses = iter(
        [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call-big",
                        "name": "huge_tool",
                        "arguments": "{}",
                    }
                ],
            },
            {
                "id": "resp-2",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "narrowing"}],
                    }
                ],
            },
        ]
    )

    def fake_post(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        requests.append(payload)
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "run huge"}],
        active_tools=[],
        run_tools=True,
        thinking_mode="disabled",
        web_search_mode="disabled",
    )

    assert out == "narrowing"
    assert len(requests) == 2
    output_item = next(
        item
        for item in _without_environment_context(requests[1]["input"])
        if item.get("type") == "function_call_output"
    )
    output_text = output_item["output"]
    assert len(output_text) < 1000
    assert "x" * 1000 not in output_text
    compact_payload = json.loads(output_text)
    assert compact_payload["status"] == "tool_result_submission_error"
    assert compact_payload["tool"] == "huge_tool"
    assert compact_payload["call_id"] == "call-big"
    assert compact_payload["original_result_chars"] == 5000
    assert "local submission limit" in compact_payload["provider_error"]
    notices = [
        event
        for event in agent.events
        if event.get("type") == "runtime_notice"
        and event.get("stage") == "tool_result_submission_compacted"
    ]
    assert len(notices) == 1
    notice_payload = json.loads(notices[0]["message"])
    assert notice_payload["tool"] == "huge_tool"
    assert notice_payload["call_id"] == "call-big"
    assert notice_payload["limit"] == 1000
    assert "provider.toolResultSubmissionMaxChars=1000" in notice_payload["summary"]


def test_openai_responses_compacts_oversized_tool_output_before_continuation_and_history_replay():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "responsesReplayReasoningItems": False,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 1000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.tools = BaseTool(agent)
    requests = []

    def huge_tool():
        return "x" * 5000

    agent.tools.function_map["huge_tool"] = huge_tool
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )

    responses = iter(
        [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-big",
                        "name": "huge_tool",
                        "arguments": "{}",
                    }
                ],
            },
            {
                "id": "resp-2",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "narrowing"}],
                    }
                ],
            },
        ]
    )

    def fake_post(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        requests.append(payload)
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "run huge"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
    )

    assert out == "narrowing"
    assert len(requests) == 2
    second_payload_text = json.dumps(requests[1]["input"], ensure_ascii=False)
    assert "x" * 1000 not in second_payload_text
    output_item = next(item for item in requests[1]["input"] if item.get("type") == "function_call_output")
    compact_payload = json.loads(output_item["output"])
    assert compact_payload["status"] == "tool_result_submission_error"
    assert compact_payload["tool"] == "huge_tool"
    assert compact_payload["call_id"] == "call-big"
    assert compact_payload["original_result_chars"] == 5000
    tool_messages = [message for message in agent.messages if message.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert json.loads(tool_messages[0]["content"]) == compact_payload
    rebuilt_context = json.dumps(agent._build_responses_input(agent.messages), ensure_ascii=False)
    assert "x" * 1000 not in rebuilt_context
    assert "tool_result_submission_error" in rebuilt_context


def test_doubao_responses_recovers_when_provider_rejects_tool_output_size():
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://example.test/v1",
        "model": "doubao-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "doubao"
    agent.messages = []
    agent.events = []
    agent.memory = SimpleNamespace(build_messages_with_memory=lambda messages: [dict(item) for item in messages])
    agent.internal_memory_enabled = False
    agent.tool_event_callback = agent.events.append
    agent.tools = BaseTool(agent)
    requests = []

    def tool_returns_provider_heavy_payload():
        return "x" * 2000

    agent.tools.function_map["heavy_tool"] = tool_returns_provider_heavy_payload
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )

    def fake_post(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        requests.append(payload)
        if len(requests) == 1:
            return {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-heavy",
                        "name": "heavy_tool",
                        "arguments": "{}",
                        "status": "completed",
                    }
                ],
            }
        if len(requests) == 2:
            raise RuntimeError(
                "responses: HTTP 400: "
                '{"error":{"message":"Total tokens of image and text exceed max message tokens"}}'
            )
        return {
            "id": "resp-3",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "use a narrower request"}],
                }
            ],
        }

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "run heavy"}],
        active_tools=[],
        run_tools=True,
        thinking_mode="disabled",
        web_search_mode="disabled",
    )

    assert out == "use a narrower request"
    assert len(requests) == 3
    assert "previous_response_id" not in requests[1]
    assert "previous_response_id" not in requests[2]
    recovered_output = next(item for item in requests[2]["input"] if item.get("type") == "function_call_output")
    recovered_payload = json.loads(recovered_output["output"])
    assert recovered_payload["status"] == "tool_result_submission_error"
    assert recovered_payload["tool"] == "heavy_tool"
    assert recovered_payload["call_id"] == "call-heavy"
    assert recovered_payload["original_result_chars"] == 2000
    assert "Total tokens" in recovered_payload["provider_error"]


def test_openai_responses_recovers_when_provider_rejects_tool_output_size():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "responsesReplayReasoningItems": False,
        "responsesMode": "whole_response",
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.events = []
    agent.memory = SimpleNamespace(build_messages_with_memory=lambda messages: [dict(item) for item in messages])
    agent.internal_memory_enabled = False
    agent.tool_event_callback = agent.events.append
    agent.tools = BaseTool(agent)
    requests = []

    def tool_returns_provider_heavy_payload():
        return "x" * 2000

    agent.tools.function_map["heavy_tool"] = tool_returns_provider_heavy_payload
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )

    def fake_post(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        requests.append(payload)
        if len(requests) == 1:
            return {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-heavy",
                        "name": "heavy_tool",
                        "arguments": "{}",
                        "status": "completed",
                    }
                ],
            }
        if len(requests) == 2:
            raise RuntimeError(
                "responses: HTTP 400: "
                '{"error":{"message":"Total tokens of image and text exceed max message tokens"}}'
            )
        return {
            "id": "resp-3",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "use a narrower request"}],
                }
            ],
        }

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "run heavy"}],
        active_tools=[],
        run_tools=True,
        web_search_mode="disabled",
    )

    assert out == "use a narrower request"
    assert len(requests) == 3
    assert "previous_response_id" not in requests[1]
    assert "previous_response_id" not in requests[2]
    recovered_output = next(item for item in requests[2]["input"] if item.get("type") == "function_call_output")
    recovered_payload = json.loads(recovered_output["output"])
    assert recovered_payload["status"] == "tool_result_submission_error"
    assert recovered_payload["tool"] == "heavy_tool"
    assert recovered_payload["call_id"] == "call-heavy"
    assert recovered_payload["original_result_chars"] == 2000
    assert "Total tokens" in recovered_payload["provider_error"]


def test_doubao_tool_result_submission_limit_requires_provider_config():
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {}

    with pytest.raises(ValueError, match="provider.toolResultSubmissionMaxChars"):
        agent._compact_tool_result_for_submission_if_needed(
            tool_name="huge_tool",
            call_id="call-big",
            content="x",
        )


def test_doubao_responses_continuation_includes_tool_image_data():
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://example.test/v1",
        "model": "doubao-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "doubao"
    agent.messages = []
    agent.tools = BaseTool(agent)
    requests = []
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )

    def fake_post(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        requests.append(payload)
        if len(requests) == 1:
            return {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
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
                    "content": [{"type": "output_text", "text": "screenshot visible"}],
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
        thinking_mode="disabled",
        web_search_mode="disabled",
    )

    assert out == "screenshot visible"
    assert len(requests) == 2
    continuation_input = _without_environment_context(requests[1]["input"])
    tool_output_index = next(
        index
        for index, item in enumerate(continuation_input)
        if item.get("type") == "function_call_output"
    )
    image_item = continuation_input[tool_output_index + 1]
    assert image_item["type"] == "message"
    assert image_item["role"] == "user"
    assert image_item["status"] == "completed"
    assert image_item["content"][0] == {"type": "input_text", "text": "Image captured by tool."}
    assert image_item["content"][1] == {
        "type": "input_image",
        "image_url": "data:image/png;base64,YWJj",
    }


def test_doubao_responses_replays_context_when_previous_response_missing():
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://example.test/v1",
        "model": "doubao-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "doubao"
    agent.messages = []
    agent.tools = BaseTool(agent)
    requests = []
    captured = []

    def echo_tool(message=None):
        captured.append(message)
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )

    def fake_post(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        requests.append(payload)
        if len(requests) == 1:
            return {
                "id": "resp-missing",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "echo_tool",
                        "arguments": '{"message":"hello"}',
                        "status": "completed",
                    }
                ],
            }
        if len(requests) == 2 and payload.get("previous_response_id"):
            raise RuntimeError(
                "HTTP Error 400: InvalidParameter.PreviousResponseNotFound: "
                "Previous response with id resp-missing not found"
            )
        return {
            "id": "resp-final",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "done"}],
                }
            ],
        }

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=True,
        thinking_mode="disabled",
        web_search_mode="disabled",
    )

    assert out == "done"
    assert captured == ["hello"]
    assert len(requests) == 2
    assert "previous_response_id" not in requests[1]
    fallback_input = _without_environment_context(requests[1]["input"])
    assert any(item.get("type") == "message" and item.get("role") == "user" for item in fallback_input)
    assert any(item == {
        "type": "function_call",
        "call_id": "call-1",
        "name": "echo_tool",
        "arguments": '{"message":"hello"}',
        "id": "fc-1",
        "status": "completed",
    } for item in fallback_input)
    tool_output = next(item for item in fallback_input if item.get("type") == "function_call_output")
    assert tool_output["call_id"] == "call-1"
    assert "echo:hello" in tool_output["output"]


def test_doubao_responses_replays_explicit_context_between_tool_rounds():
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://example.test/v1",
        "model": "doubao-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolResultSubmissionMaxChars": 50000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "doubao"
    agent.messages = []
    agent.tools = BaseTool(agent)
    requests = []
    captured = []

    def echo_tool(message=None):
        captured.append(message)
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )

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
                    }
                ],
            },
            {
                "id": "resp-2",
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
        payload = json.loads(kwargs["payload_json"])
        requests.append(payload)
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=True,
        thinking_mode="disabled",
        web_search_mode="disabled",
    )

    assert out == "done"
    assert captured == ["hello"]
    assert len(requests) == 2
    assert "previous_response_id" not in requests[1]
    fallback_input = _without_environment_context(requests[1]["input"])
    assert fallback_input[0]["role"] == "user"
    assert fallback_input[1]["type"] == "function_call"
    assert fallback_input[2]["type"] == "function_call_output"
    assert fallback_input[2]["call_id"] == "call-1"


def test_openai_responses_payload_includes_reasoning_effort():
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
        reasoning_effort="xhigh",
    )

    assert out == "ok"
    assert payloads[0]["reasoning"] == {"effort": "xhigh", "summary": "auto"}


def test_openai_responses_payload_allows_reasoning_summary_override():
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
        reasoning_effort="xhigh",
        reasoning_summary="concise",
    )

    assert out == "ok"
    assert payloads[0]["reasoning"] == {"effort": "xhigh", "summary": "concise"}


def test_openai_stream_uses_response_call_id_not_function_item_id(monkeypatch):
    import json as json_module

    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {"timeoutMs": 1000}
    agent.provider_name = "openai"
    events = [
        {
            "type": "response.output_item.added",
            "item": {"type": "function_call", "id": "fc_item_1", "name": "echo_tool"},
        },
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "fc_item_1",
            "delta": '{"message":"hello"}',
        },
        {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "id": "fc_item_1",
                "call_id": "call_real_1",
                "name": "echo_tool",
                "arguments": '{"message":"hello"}',
            },
        },
    ]
    monkeypatch.setattr(agent, "_curl_post_sse_data_lines", lambda **_kwargs: (json_module.dumps(event) for event in events))

    result = agent._stream_responses_once(
        url="https://api.openai.test/v1/responses",
        headers={},
        payload_json="{}",
        timeout_sec=1,
        stream_handler=None,
    )

    assert result["output"][0]["id"] == "fc_item_1"
    assert result["output"][0]["call_id"] == "call_real_1"
    assert result["output"][0]["arguments"] == '{"message":"hello"}'


def test_openai_stream_repairs_completed_response_function_call_id(monkeypatch):
    import json as json_module

    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {"timeoutMs": 1000}
    agent.provider_name = "openai"
    events = [
        {
            "type": "response.output_item.added",
            "item": {"type": "function_call", "id": "fc_item_1", "name": "echo_tool"},
        },
        {
            "type": "response.output_item.done",
            "item": {
                "type": "function_call",
                "id": "fc_item_1",
                "call_id": "call_real_1",
                "name": "echo_tool",
                "arguments": '{"message":"hello"}',
            },
        },
        {
            "type": "response.completed",
            "response": {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc_item_1",
                        "name": "echo_tool",
                        "arguments": '{"message":"hello"}',
                    }
                ],
            },
        },
    ]
    monkeypatch.setattr(agent, "_curl_post_sse_data_lines", lambda **_kwargs: (json_module.dumps(event) for event in events))

    result = agent._stream_responses_once(
        url="https://api.openai.test/v1/responses",
        headers={},
        payload_json="{}",
        timeout_sec=1,
        stream_handler=None,
    )
    _content, calls, _response_id = agent._parse_responses_output_envelopes(result)

    assert result["output"][0]["call_id"] == "call_real_1"
    assert calls[0].call_id == "call_real_1"


def test_openai_stream_retries_response_failed_503(monkeypatch):
    import json as json_module

    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {"timeoutMs": 1000}
    agent.provider_name = "openai"
    agent.events = []
    agent.tool_event_callback = agent.events.append
    calls = {"count": 0}
    failed_event = {
        "type": "response.failed",
        "response": {
            "error": {"status_code": 503, "code": "service_unavailable", "message": "busy"}
        },
    }
    success_event = {
        "type": "response.completed",
        "response": {
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "ok"}]}
            ]
        },
    }
    def fake_sse_lines(**_kwargs):
        calls["count"] += 1
        event = failed_event if calls["count"] == 1 else success_event
        yield json_module.dumps(event)

    monkeypatch.setattr(agent, "_curl_post_sse_data_lines", fake_sse_lines)
    monkeypatch.setattr(
        "src.providers.openai_retry_transport.sleep_with_cancel",
        lambda _seconds, _cancel: None,
    )
    result = agent._stream_responses_with_retry(
        endpoint="responses",
        url="https://api.openai.test/v1/responses",
        headers={},
        payload_json="{}",
        stream_handler=None,
    )

    assert calls["count"] == 2
    assert result["output"][0]["content"][0]["text"] == "ok"
    notices_by_stage = {
        event.get("stage"): event
        for event in agent.events
        if event.get("type") == "runtime_notice"
    }
    assert "openai_responses_sse_failure_debug" in notices_by_stage
    assert "openai_responses_retry" in notices_by_stage
    assert "503" in notices_by_stage["openai_responses_retry"]["message"]


def test_openai_stream_does_not_retry_account_quota_exceeded(monkeypatch):
    import json as json_module

    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {"timeoutMs": 1000, "maxRetries": 5, "retryDelaySec": 0}
    agent.provider_name = "openai"
    agent.events = []
    agent.tool_event_callback = agent.events.append
    calls = {"count": 0}
    failed_event = {
        "type": "response.failed",
        "response": {
            "error": {
                "status_code": 429,
                "code": "AccountQuotaExceeded",
                "message": "You have exceeded the 5-hour usage quota.",
            }
        },
    }

    def fake_sse_lines(**_kwargs):
        calls["count"] += 1
        yield json_module.dumps(failed_event)

    monkeypatch.setattr(agent, "_curl_post_sse_data_lines", fake_sse_lines)
    monkeypatch.setattr(
        "src.providers.openai_retry_transport.sleep_with_cancel",
        lambda _seconds, _cancel: None,
    )

    with pytest.raises(RuntimeError, match="AccountQuotaExceeded"):
        agent._stream_responses_with_retry(
            endpoint="responses",
            url="https://api.openai.test/v1/responses",
            headers={},
            payload_json="{}",
            stream_handler=None,
        )

    assert calls["count"] == 1
    assert [event.get("stage") for event in agent.events] == ["openai_responses_sse_failure_debug"]


def test_openai_responses_continuation_replays_explicit_context():
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
    captured = []
    requests = []

    def echo_tool(message=None):
        captured.append(message)
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )

    responses = iter(
        [
            {
                "id": "resp-1",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc_real_1",
                        "call_id": "call_real_1",
                        "name": "echo_tool",
                        "arguments": '{"message":"hello"}',
                        "status": "completed",
                    }
                ],
            },
            {
                "id": "resp-2",
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
        requests.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
    )

    assert out == "done"
    assert captured == ["hello"]
    assert len(requests) == 2
    second_input = _without_environment_context(requests[1]["input"])
    assert "previous_response_id" not in requests[1]
    assert any(item == {
        "type": "function_call",
        "call_id": "call_real_1",
        "name": "echo_tool",
        "arguments": '{"message":"hello"}',
        "id": "fc_real_1",
        "status": "completed",
    } for item in second_input)
    assert any(item == {
        "type": "function_call_output",
        "call_id": "call_real_1",
        "output": "echo:hello",
        "status": "completed",
    } for item in second_input)
    turn_events = _runtime_notice_payloads(agent.events, "openai_responses_turn")
    assert turn_events[0]["response_id_present"] is True
    assert turn_events[0]["response_id"] == "resp-1"
    assert turn_events[0]["next_continuation_mode"] == "explicit_context"
    assert turn_events[0]["followup_item_count"] == 1
    assert turn_events[1]["next_continuation_mode"] == "final_message"


def test_openai_responses_logs_explicit_context_when_response_id_missing():
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
    requests = []

    def echo_tool(message=None):
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )

    responses = iter(
        [
            {
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc_real_1",
                        "call_id": "call_real_1",
                        "name": "echo_tool",
                        "arguments": '{"message":"hello"}',
                        "status": "completed",
                    }
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
        requests.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
    )

    assert out == "done"
    assert len(requests) == 2
    assert "previous_response_id" not in requests[1]
    turn_events = _runtime_notice_payloads(agent.events, "openai_responses_turn")
    assert turn_events[0]["response_id_present"] is False
    assert turn_events[0]["response_id"] == ""
    assert turn_events[0]["next_continuation_mode"] == "explicit_context"
    assert turn_events[0]["followup_item_count"] == 1


def test_openai_responses_replays_context_when_previous_response_missing():
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
    requests = []
    captured = []

    def echo_tool(message=None):
        captured.append(message)
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )

    def fake_post(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        requests.append(payload)
        if len(requests) == 1:
            return {
                "id": "resp-missing",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc_real_1",
                        "call_id": "call_real_1",
                        "name": "echo_tool",
                        "arguments": '{"message":"hello"}',
                        "status": "completed",
                    }
                ],
            }
        if len(requests) == 2 and payload.get("previous_response_id"):
            raise RuntimeError("responses: HTTP 400 - previous_response_id not found")
        return {
            "id": "resp-final",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "done"}],
                }
            ],
        }

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    out = agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
    )

    assert out == "done"
    assert captured == ["hello"]
    assert len(requests) == 2
    assert "previous_response_id" not in requests[1]
    fallback_input = _without_environment_context(requests[1]["input"])
    assert any(item == {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "run echo"}],
        "status": "completed",
    } for item in fallback_input)
    assert any(item == {
        "type": "function_call",
        "call_id": "call_real_1",
        "name": "echo_tool",
        "arguments": '{"message":"hello"}',
        "id": "fc_real_1",
        "status": "completed",
    } for item in fallback_input)
    assert any(item == {
        "type": "function_call_output",
        "call_id": "call_real_1",
        "output": "echo:hello",
        "status": "completed",
    } for item in fallback_input)
    fallback_events = _runtime_notice_payloads(agent.events, "openai_responses_previous_response_missing")
    assert fallback_events == []


def test_openai_responses_rebuilds_input_after_tool_context_compaction():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "maxRetries": 0,
        "retryDelaySec": 0,
        "toolContextCompactionEnabled": True,
        "toolContextCompactionEveryToolCalls": 1,
        "toolContextCompactionInputTokens": 0,
        "toolContextCompactionCurrentInputTokens": 0,
        "toolContextCompactionOutputTokens": 0,
        "responsesReplayReasoningItems": False,
        "toolResultSubmissionMaxChars": 50000,
    }
    agent.provider_name = "openai"
    agent.messages = [{"role": "user", "content": "run echo"}]
    agent.tools = BaseTool(agent)
    agent._tool_context_compaction_window = ToolContextCompactionWindow()
    agent.internal_memory_enabled = False
    agent.system_prompt = None
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    echo_calls = []

    def echo_tool(message=None):
        echo_calls.append(message)
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool
    requests = []

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
                    }
                ],
            },
            {
                "id": "resp-compact",
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc-compact",
                        "call_id": "call-compact",
                        "name": "compact_tool_context",
                        "arguments": json.dumps(
                            {
                                "action": "replace",
                                "reason": "Replace the completed echo exchange.",
                                "summary": {
                                    "task_anchor": "Run echo and finish the original task.",
                                    "completed_facts": [
                                        "The echo tool returned echo:hello."
                                    ],
                                    "changed_state": [],
                                    "verification": ["The echo result was observed."],
                                    "failed_attempts": [],
                                    "remaining_steps": ["Continue the original task."],
                                    "immediate_next_step": "Continue the original task.",
                                    "avoid_repeating": ["Do not call echo_tool again."],
                                },
                            }
                        ),
                    },
                    {
                        "type": "function_call",
                        "id": "fc-unoffered",
                        "call_id": "call-unoffered",
                        "name": "echo_tool",
                        "arguments": '{"message":"must-not-run"}',
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
        requests.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    out = agent._send_via_responses(
        messages=list(agent.messages),
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
    )

    assert out == "done"
    assert len(requests) == 3
    gate_tools = [item.get("name") for item in requests[1]["tools"] if item.get("type") == "function"]
    assert gate_tools == ["compact_tool_context"]
    gate_input_text = json.dumps(requests[1]["input"], ensure_ascii=False)
    assert "echo:hello" in gate_input_text
    assert "Compaction input:" not in gate_input_text
    assert gate_input_text.count("echo:hello") < 4

    final_input_text = json.dumps(requests[2]["input"], ensure_ascii=False)
    assert "[Tool Context Summary]" in final_input_text
    assert "echo:hello" in final_input_text
    assert "function_call_output" not in final_input_text
    assert "compact_tool_context" not in final_input_text
    assert "call-unoffered" not in final_input_text
    assert echo_calls == ["hello"]


def test_openai_responses_accepts_final_text_at_compaction_checkpoint():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://example.com/v1",
        "model": "gpt-test",
        "responsesApi": True,
        "toolContextCompactionEnabled": True,
        "toolContextCompactionEveryToolCalls": 1,
        "toolContextCompactionInputTokens": 0,
        "toolContextCompactionCurrentInputTokens": 0,
        "toolContextCompactionOutputTokens": 0,
        "toolResultSubmissionMaxChars": 50000,
    }
    agent.provider_name = "openai"
    agent.messages = [{"role": "user", "content": "run echo"}]
    agent.tools = BaseTool(agent)
    agent._tool_context_compaction_window = ToolContextCompactionWindow()
    agent.internal_memory_enabled = False
    agent.system_prompt = None
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    agent.tools.function_map["echo_tool"] = lambda message=None: f"echo:{message}"
    requests = []
    responses = iter(
        [
            {
                "id": "resp-tool",
                "output": [
                    {
                        "type": "function_call",
                        "call_id": "call-echo",
                        "name": "echo_tool",
                        "arguments": '{"message":"hello"}',
                    }
                ],
            },
            {
                "id": "resp-final",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "The task is complete."}],
                    }
                ],
            },
        ]
    )

    def fake_post(**kwargs):
        requests.append(json.loads(kwargs["payload_json"]))
        return next(responses)

    agent._post_json_with_retry = fake_post
    agent._stream_responses_with_retry = fake_post

    out = agent._send_via_responses(
        messages=list(agent.messages),
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
    )

    assert out == "The task is complete."
    assert len(requests) == 2
    assert [item.get("name") for item in requests[1]["tools"] if item.get("type") == "function"] == [
        "compact_tool_context"
    ]
    assert agent._tool_context_compaction_gate_active is False
    assert "compact_tool_context" not in agent.tools.function_map
    assert agent.messages[-1]["content"] == "The task is complete."


def test_openai_responses_rejects_function_item_id_as_call_id():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)

    with pytest.raises(ValueError, match="output item id"):
        agent._parse_responses_output_envelopes(
            {
                "output": [
                    {
                        "type": "function_call",
                        "id": "fc_real_1",
                        "call_id": "fc_real_1",
                        "name": "echo_tool",
                        "arguments": "{}",
                    }
                ]
            }
        )


def test_doubao_inject_image_message_reports_missing_image(tmp_path):
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.messages = []

    missing = tmp_path / "missing.png"
    with pytest.raises(ProviderImageAttachmentError, match="image file not found"):
        agent._inject_image_message(str(missing))

    assert agent.messages == []


def test_gemini_function_response_content_parses_only_json_objects():
    from src.providers.gemini_message_mapping import build_function_response_content

    assert build_function_response_content('{"status":"ok"}') == {"status": "ok"}
    assert build_function_response_content("[1, 2]") == {"result": "[1, 2]"}
    assert build_function_response_content("plain text") == {"result": "plain text"}


def test_gemini_tool_schema_preserves_action_specific_composites():
    from functions.operational_memory_tools import edit_operational_memory_declaration
    from src.providers.gemini_agent import GeminiAgent

    agent = GeminiAgent.__new__(GeminiAgent)
    converted = agent._convert_tool_to_gemini(edit_operational_memory_declaration)
    params = converted["parameters"]

    assert params["type"] == "OBJECT"
    assert isinstance(params["oneOf"], list)
    resolve_branch = next(
        item
        for item in params["oneOf"]
        if item.get("properties", {}).get("action", {}).get("enum") == ["resolve"]
    )
    assert resolve_branch["anyOf"] == [{"required": ["key"]}, {"required": ["resolve_key"]}]


def test_gemini_send_reports_missing_local_image(tmp_path):
    from src.providers.gemini_agent import GeminiAgent

    agent = GeminiAgent.__new__(GeminiAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://example.test/v1",
        "model": "gemini-test",
        "maxRetries": 0,
        "retryDelaySec": 0,
        "timeoutMs": 1000,
    }
    agent.messages = [
        {
            "role": "user",
            "content": {
                "type": "image",
                "path": str(tmp_path / "missing.png"),
                "text": "inspect",
            },
        }
    ]
    agent.tools = BaseTool(agent)
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )

    with pytest.raises(ProviderImageAttachmentError, match="failed to read image file"):
        agent.Send(run_tools=False)
