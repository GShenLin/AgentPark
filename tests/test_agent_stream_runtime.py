import pytest

from nodes.agent_stream_runtime import AgentStreamRuntime


def test_agent_stream_runtime_emits_delta_tool_event_and_done():
    events = []
    runtime = AgentStreamRuntime(lambda payload: events.append(payload))

    runtime.on_stream_delta("A", "A")
    runtime.on_tool_event({"type": "tool_call_start", "name": "read_file"})
    runtime.emit_done("AB")

    assert events == [
        {"type": "node_message_delta", "delta": "A", "text": "A"},
        {"type": "tool_call_start", "name": "read_file"},
        {"type": "node_message_delta", "delta": "B", "text": "AB", "force": True},
        {"type": "node_message_done", "text": "AB"},
    ]


def test_agent_stream_runtime_emits_thinking_delta_separately():
    events = []
    runtime = AgentStreamRuntime(lambda payload: events.append(payload))

    runtime.on_thinking_delta("plan", "plan", "openai_responses")
    runtime.on_stream_delta("Answer", "Answer")

    assert events == [
        {
            "type": "node_thinking_delta",
            "delta": "plan",
            "text": "plan",
            "provider": "openai_responses",
        },
        {"type": "node_message_delta", "delta": "Answer", "text": "Answer"},
    ]


def test_agent_stream_runtime_emits_refusal_and_uses_it_as_final_text():
    events = []
    runtime = AgentStreamRuntime(lambda payload: events.append(payload))

    runtime.on_tool_event(
        {
            "type": "response_refusal",
            "item_id": "msg_1",
            "delta": "I cannot help.",
            "text": "I cannot help.",
            "status": "completed",
        }
    )
    runtime.emit_done("")

    assert events[0]["type"] == "response_refusal"
    assert events[-2] == {
        "type": "node_message_delta",
        "delta": "I cannot help.",
        "text": "I cannot help.",
        "force": True,
    }
    assert events[-1] == {"type": "node_message_done", "text": "I cannot help."}


def test_agent_stream_runtime_carries_server_tool_result_into_done_event():
    events = []
    runtime = AgentStreamRuntime(lambda payload: events.append(payload))
    runtime.on_tool_event(
        {
            "type": "server_tool_activity",
            "call_id": "ws_1",
            "tool_type": "web_search",
            "status": "completed",
            "sources": [{"url": "https://example.com", "title": "Example"}],
        }
    )

    runtime.emit_done(
        "answer",
        structured_result={
            "citations": [{"url": "https://example.com"}],
            "response_metadata": {
                "protocol": "responses",
                "response": {"id": "resp_1", "status": "completed"},
                "output_items": [],
            },
        },
    )

    assert events[-1] == {
        "type": "node_message_done",
        "text": "answer",
        "server_tool_calls": [
            {
                "call_id": "ws_1",
                "tool_type": "web_search",
                "status": "completed",
                "sources": [{"url": "https://example.com", "title": "Example"}],
            }
        ],
        "citations": [{"url": "https://example.com"}],
        "response_metadata": {
            "protocol": "responses",
            "response": {"id": "resp_1", "status": "completed"},
            "output_items": [],
        },
    }


def test_agent_stream_runtime_restores_tool_callback_after_send():
    previous_events = []

    class Agent:
        def __init__(self):
            self.tool_event_callback = previous_events.append

        def Send(self, **kwargs):
            assert callable(self.tool_event_callback)
            self.tool_event_callback({"type": "tool_call_start", "name": "read_file"})
            handler = kwargs.get("stream_handler")
            if callable(handler):
                handler("O", "O")
            return "ok"

    events = []
    agent = Agent()
    previous_callback = agent.tool_event_callback
    runtime = AgentStreamRuntime(lambda payload: events.append(payload))

    response = runtime.send(agent, {"stream_handler": runtime.on_stream_delta})

    assert response == "ok"
    assert agent.tool_event_callback is previous_callback
    assert previous_events == []
    assert events == [
        {"type": "tool_call_start", "name": "read_file"},
        {"type": "node_message_delta", "delta": "O", "text": "O"},
    ]


def test_agent_stream_runtime_accepts_tool_event_callback_keyword():
    stream_events = []
    tool_events = []
    runtime = AgentStreamRuntime(
        lambda payload: stream_events.append(payload),
        tool_event_callback=lambda payload: tool_events.append(payload),
    )

    runtime.on_tool_event({"type": "tool_call_start", "name": "read_file"})

    assert tool_events == [{"type": "tool_call_start", "name": "read_file"}]
    assert stream_events == [{"type": "tool_call_start", "name": "read_file"}]


def test_agent_stream_runtime_attaches_runtime_tool_call_arguments_and_result():
    runtime = AgentStreamRuntime(None)
    runtime.on_tool_event(
        {
            "type": "tool_call_start",
            "name": "execute_console_command",
            "call_id": "call_1",
            "provider": "responses",
            "arguments": {"command": "Get-Location"},
            "arguments_json": '{"command":"Get-Location"}',
            "raw_call": {"type": "function_call"},
        }
    )
    runtime.on_tool_event(
        {
            "type": "tool_call_end",
            "name": "execute_console_command",
            "call_id": "call_1",
            "provider": "responses",
            "status": "completed",
            "duration_ms": 12,
            "result": '{"stdout":"C:\\\\Project","stderr":"","returncode":0}',
        }
    )

    result = runtime.attach_runtime_tool_calls(
        {"response": "done", "response_metadata": {"protocol": "responses"}}
    )

    assert result["response_metadata"]["runtime_tool_calls"] == [
        {
            "name": "execute_console_command",
            "call_id": "call_1",
            "provider": "responses",
            "arguments": {"command": "Get-Location"},
            "status": "completed",
            "duration_ms": 12,
            "result": '{"stdout":"C:\\\\Project","stderr":"","returncode":0}',
        }
    ]


def test_agent_stream_runtime_filters_unsupported_kwargs_and_restores_tool_callback():
    class Agent:
        def __init__(self):
            self.tool_event_callback = lambda _payload: None
            self.kwargs = None

        def Send(self, run_tools=False):
            self.kwargs = {"run_tools": run_tools}
            return "ok"

    agent = Agent()
    previous_callback = agent.tool_event_callback
    runtime = AgentStreamRuntime(None)

    response = runtime.send(agent, {"run_tools": True, "stream": True})

    assert response == "ok"
    assert agent.kwargs == {"run_tools": True}
    assert agent.tool_event_callback is previous_callback


def test_agent_stream_runtime_does_not_retry_internal_type_error():
    class Agent:
        def __init__(self):
            self.tool_event_callback = lambda _payload: None
            self.calls = 0

        def Send(self, run_tools=False):
            self.calls += 1
            raise TypeError("internal send failure")

    agent = Agent()
    previous_callback = agent.tool_event_callback
    runtime = AgentStreamRuntime(None)

    with pytest.raises(TypeError, match="internal send failure"):
        runtime.send(agent, {"run_tools": True, "stream": True})

    assert agent.calls == 1
    assert agent.tool_event_callback is previous_callback


def test_agent_stream_runtime_propagates_callback_errors_by_default():
    runtime = AgentStreamRuntime(lambda _payload: (_ for _ in ()).throw(RuntimeError("sink failed")))

    with pytest.raises(RuntimeError, match="sink failed"):
        runtime.on_tool_event({"type": "tool_call_start", "name": "read_file"})


def test_agent_stream_runtime_can_suppress_callback_errors_explicitly():
    runtime = AgentStreamRuntime(
        lambda _payload: (_ for _ in ()).throw(RuntimeError("sink failed")),
        suppress_callback_errors=True,
    )

    runtime.on_tool_event({"type": "tool_call_start", "name": "read_file"})
