import json
import threading

import pytest

from nodes.agent_stream_runtime import AgentStreamRuntime
from src.providers.openai_responses_stream_normalizer import OpenAIResponsesStreamEventNormalizer
from src.tool.base_tool import BaseTool


def _openai_agent():
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "apiKey": "test",
        "baseUrl": "https://api.openai.test/v1",
        "model": "gpt-test",
        "maxRetries": 0,
        "retryDelaySec": 0,
        "responsesApi": True,
        "responsesContinuationMode": "explicit_context",
        "responsesReplayReasoningItems": False,
    }
    agent.provider_name = "openai"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    return agent


def _emit_item_events(handler, raw_events):
    normalizer = OpenAIResponsesStreamEventNormalizer()
    for raw_event in raw_events:
        for event in normalizer.ingest_event(raw_event):
            handler(event)


def test_item_level_runtime_starts_tool_when_function_call_item_done():
    agent = _openai_agent()
    agent.events = []
    agent.tool_event_callback = agent.events.append
    payloads = []
    order = []
    tool_started = threading.Event()
    release_tool = threading.Event()

    def echo_tool(message=None):
        order.append("tool_started")
        tool_started.set()
        release_tool.wait(timeout=2)
        order.append("tool_finished")
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool

    def fake_stream(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        if len(payloads) == 1:
            _emit_item_events(
                kwargs["item_event_handler"],
                [
                    {
                        "type": "response.output_item.added",
                        "item": {"type": "function_call", "id": "fc-1", "name": "echo_tool"},
                    },
                    {
                        "type": "response.output_item.done",
                        "item": {
                            "type": "function_call",
                            "id": "fc-1",
                            "call_id": "call-1",
                            "name": "echo_tool",
                            "arguments": '{"message":"hello"}',
                        },
                    },
                ],
            )
            assert tool_started.wait(timeout=1)
            order.append("response_completed_returned")
            release_tool.set()
            return {
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
            }
        return {
            "id": "resp-final",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "done"}]},
            ],
        }

    agent._stream_responses_with_retry = fake_stream

    assert agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
    ) == "done"

    assert payloads[0]["stream"] is True
    assert order.index("tool_started") < order.index("response_completed_returned")
    assert payloads[1]["input"][1]["type"] == "function_call"
    assert payloads[1]["input"][2] == {
        "type": "function_call_output",
        "call_id": "call-1",
        "output": "echo:hello",
        "status": "completed",
    }
    notices = [
        json.loads(event["message"])
        for event in agent.events
        if event.get("type") == "runtime_notice" and event.get("stage") == "openai_responses_turn"
    ]
    assert notices[0]["requested_responses_mode"] == "responses_api"
    assert notices[0]["responses_mode"] == "item_level"
    assert notices[0]["responses_mode_fallback_reason"] == ""


def test_item_level_runtime_run_tools_false_returns_function_call_without_execution():
    agent = _openai_agent()
    payloads = []

    def echo_tool(message=None):
        raise AssertionError("run_tools=false must not execute tools")

    agent.tools.function_map["echo_tool"] = echo_tool

    def fake_stream(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        _emit_item_events(
            kwargs["item_event_handler"],
            [
                {
                    "type": "response.output_item.done",
                    "item": {
                        "type": "function_call",
                        "id": "fc-1",
                        "call_id": "call-1",
                        "name": "echo_tool",
                        "arguments": '{"message":"hello"}',
                    },
                }
            ],
        )
        return {
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
        }

    agent._stream_responses_with_retry = fake_stream

    result = agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=False,
        reasoning_effort="",
    )

    assert result["type"] == "function_call"
    assert result["tool_calls"][0]["id"] == "call-1"
    assert payloads[0]["stream"] is True
    assert len(agent.messages) == 1
    assert agent.messages[0]["role"] == "assistant"
    assert agent.messages[0]["tool_calls"][0]["id"] == "call-1"


def test_responses_runtime_requires_responses_api_support():
    agent = _openai_agent()
    agent.config["responsesApi"] = False

    with pytest.raises(ValueError, match="responsesApi=true"):
        agent._send_via_responses(
            messages=[{"role": "user", "content": "run echo"}],
            active_tools=[],
            run_tools=True,
            reasoning_effort="",
        )


def test_item_level_runtime_interleaves_tool_events_with_assistant_deltas():
    agent = _openai_agent()
    stream_events = []
    runtime = AgentStreamRuntime(lambda payload: stream_events.append(payload))
    agent.tool_event_callback = runtime.on_tool_event
    tool_started = threading.Event()
    release_tool = threading.Event()
    payloads = []

    def echo_tool(message=None):
        tool_started.set()
        release_tool.wait(timeout=2)
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool

    def fake_stream(**kwargs):
        payloads.append(json.loads(kwargs["payload_json"]))
        handler = kwargs.get("stream_handler")
        if len(payloads) == 1:
            handler("A", "A")
            _emit_item_events(
                kwargs["item_event_handler"],
                [
                    {
                        "type": "response.output_item.done",
                        "item": {
                            "type": "function_call",
                            "id": "fc-1",
                            "call_id": "call-1",
                            "name": "echo_tool",
                            "arguments": '{"message":"hello"}',
                        },
                    }
                ],
            )
            assert tool_started.wait(timeout=1)
            handler("B", "AB")
            release_tool.set()
            return {
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
            }
        return {
            "id": "resp-final",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": "done"}]},
            ],
        }

    agent._stream_responses_with_retry = fake_stream

    assert agent._send_via_responses(
        messages=[{"role": "user", "content": "run echo"}],
        active_tools=[],
        run_tools=True,
        reasoning_effort="",
        stream_handler=runtime.on_stream_delta,
    ) == "done"

    event_types = [event["type"] for event in stream_events]
    first_delta = event_types.index("node_message_delta")
    tool_start = event_types.index("tool_call_start")
    second_delta = event_types.index("node_message_delta", first_delta + 1)
    tool_end = event_types.index("tool_call_end")
    assert first_delta < tool_start < second_delta < tool_end
    assert stream_events[first_delta]["text"] == "A"
    assert stream_events[second_delta]["text"] == "AB"
    assert stream_events[tool_start]["call_id"] == "call-1"
    assert stream_events[tool_end]["status"] == "completed"
