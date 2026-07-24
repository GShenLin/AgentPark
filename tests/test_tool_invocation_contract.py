from __future__ import annotations

import json

from src.tool.tool_function_execution import execute_local_tool_function


def _sample_tool(required, optional=None, agent=None):
    return {
        "required": required,
        "optional": optional,
        "agent": agent,
    }


def test_invalid_top_level_arguments_return_exact_retry_contract():
    result = execute_local_tool_function(
        func=_sample_tool,
        args={"required": "value", "response_length": "long"},
        agent=object(),
        tool_name="sample_tool",
        timeout_seconds=None,
        cancel_source=None,
    )

    payload = json.loads(result.model_output())
    assert result.status == "invalid_arguments"
    assert payload["status"] == "invalid_arguments"
    assert "response_length" in payload["error"]
    assert "Supplied top-level keys: ['required', 'response_length']" in payload["error"]
    assert "Expected top-level keys: ['optional', 'required']" in payload["error"]
    assert "Retry using only the declared top-level keys." in payload["error"]


def test_internal_type_error_remains_an_execution_exception():
    def broken_tool(value):
        _ = value
        raise TypeError("internal implementation failure")

    result = execute_local_tool_function(
        func=broken_tool,
        args={"value": 1},
        agent=object(),
        tool_name="broken_tool",
        timeout_seconds=None,
        cancel_source=None,
    )

    assert result.status == "exception"
    assert result.error == "TypeError: internal implementation failure"


def test_valid_arguments_bind_agent_without_exposing_it_to_the_model():
    agent = object()

    result = execute_local_tool_function(
        func=_sample_tool,
        args={"required": "value"},
        agent=agent,
        tool_name="sample_tool",
        timeout_seconds=None,
        cancel_source=None,
    )

    assert result.status == "completed"
    assert result.result == {
        "required": "value",
        "optional": None,
        "agent": agent,
    }
