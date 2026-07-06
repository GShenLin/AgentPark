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
