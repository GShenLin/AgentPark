import pytest

from src.base_tool import BaseTool
from src.providers.provider_errors import ProviderImageAttachmentError
from src.tool_call_protocol import ToolCallExecution


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
    from src.tool_call_protocol import ToolCallEnvelope

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


def test_doubao_responses_runtime_uses_envelopes_for_tool_continuation():
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://example.test/v1",
        "model": "doubao-test",
        "maxRetries": 0,
        "retryDelaySec": 0,
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
    assert '"previous_response_id": "resp-1"' in second_payload


def test_doubao_inject_image_message_reports_missing_image(tmp_path):
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.messages = []

    missing = tmp_path / "missing.png"
    with pytest.raises(ProviderImageAttachmentError, match="image file not found"):
        agent._inject_image_message(str(missing))

    assert agent.messages == []


def test_gemini_function_response_content_parses_only_json_objects():
    from src.providers.gemini_agent import GeminiAgent

    assert GeminiAgent._build_function_response_content('{"status":"ok"}') == {"status": "ok"}
    assert GeminiAgent._build_function_response_content("[1, 2]") == {"result": "[1, 2]"}
    assert GeminiAgent._build_function_response_content("plain text") == {"result": "plain text"}


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
