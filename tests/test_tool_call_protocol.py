import pytest
import json

from src.tool_call_protocol import build_tool_call_error_execution
from src.tool_call_protocol import from_gemini_function_call
from src.tool_call_protocol import from_openai_tool_call
from src.tool_call_protocol import from_responses_function_call
from src.tool_call_protocol import to_openai_tool_call


def test_openai_tool_call_round_trips_through_envelope():
    raw = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "read_file", "arguments": '{"filePath":"a.txt"}'},
    }

    call = from_openai_tool_call(raw)

    assert call is not None
    assert call.name == "read_file"
    assert call.call_id == "call-1"
    assert call.arguments == {"filePath": "a.txt"}
    assert to_openai_tool_call(call) == raw


def test_responses_function_call_converts_to_openai_tool_call_shape():
    raw = {
        "type": "function_call",
        "call_id": "call-2",
        "name": "rg_search_text",
        "arguments": {"pattern": "Agent"},
    }

    call = from_responses_function_call(raw)

    assert call is not None
    assert call.name == "rg_search_text"
    assert call.call_id == "call-2"
    assert call.arguments == {"pattern": "Agent"}
    assert to_openai_tool_call(call)["function"]["arguments"] == '{"pattern": "Agent"}'


def test_doubao_responses_parser_returns_tool_call_envelopes():
    from src.providers.doubao_agent import DouBaoAgent

    agent = DouBaoAgent.__new__(DouBaoAgent)
    result = {
        "id": "resp-1",
        "output": [
            {
                "type": "function_call",
                "call_id": "call-1",
                "name": "read_file",
                "arguments": '{"filePath":"README.md"}',
            },
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "checking"}],
            },
        ],
    }

    text, calls, response_id = agent._parse_responses_output_envelopes(result)

    assert text == "checking"
    assert response_id == "resp-1"
    assert len(calls) == 1
    assert calls[0].name == "read_file"
    assert calls[0].call_id == "call-1"
    assert calls[0].arguments == {"filePath": "README.md"}


def test_gemini_function_call_converts_to_envelope():
    call = from_gemini_function_call({"name": "project_overview", "args": {"filePath": "."}})

    assert call is not None
    assert call.provider == "gemini"
    assert call.call_id.startswith("gemini-")
    assert call.name == "project_overview"
    assert call.arguments == {"filePath": "."}


def test_missing_provider_call_id_gets_runtime_unique_id():
    first = from_openai_tool_call(
        {
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"filePath":"a.txt"}'},
        },
        provider="unit",
    )
    second = from_openai_tool_call(
        {
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"filePath":"a.txt"}'},
        },
        provider="unit",
    )

    assert first is not None
    assert second is not None
    assert first.call_id != second.call_id
    assert first.call_id.startswith("unit-")
    assert second.call_id.startswith("unit-")


def test_invalid_tool_arguments_are_rejected():
    with pytest.raises(ValueError, match="failed to parse tool arguments JSON"):
        from_openai_tool_call(
            {
                "id": "call-bad",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"filePath":'},
            }
        )


def test_build_tool_call_error_execution_uses_envelope_identity():
    call = from_openai_tool_call(
        {
            "id": "call-timeout",
            "type": "function",
            "function": {"name": "read_file", "arguments": '{"filePath":"a.txt"}'},
        },
        provider="unit",
    )

    execution = build_tool_call_error_execution(call, status="timeout", error="too slow")

    assert execution.func_name == "read_file"
    assert execution.call_id == "call-timeout"
    assert execution.status == "timeout"
    assert execution.error == "too slow"
    assert json.loads(execution.cleaned_result) == {
        "status": "timeout",
        "tool": "read_file",
        "error": "too slow",
    }
