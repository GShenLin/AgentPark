import json
import threading

from src.providers.openai_responses_stream_normalizer import OpenAIResponsesStreamEventNormalizer
from src.runtime_cancellation import CancellationRequested
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
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    return agent


def _emit_item_event(handler):
    normalizer = OpenAIResponsesStreamEventNormalizer()
    raw_event = {
        "type": "response.output_item.done",
        "item": {
            "type": "function_call",
            "id": "fc-1",
            "call_id": "call-1",
            "name": "echo_tool",
            "arguments": '{"message":"hello"}',
        },
    }
    for event in normalizer.ingest_event(raw_event):
        handler(event)


def _abort_notices(agent):
    return [
        json.loads(event["message"])
        for event in agent.events
        if event.get("type") == "runtime_notice"
        and event.get("stage") == "openai_responses_item_level_abort"
    ]


def test_item_level_runtime_reports_stream_failure_after_tool_started():
    agent = _openai_agent()
    tool_started = threading.Event()
    release_tool = threading.Event()

    def echo_tool(message=None):
        tool_started.set()
        release_tool.wait(timeout=2)
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool

    def fake_stream(**kwargs):
        _emit_item_event(kwargs["item_event_handler"])
        assert tool_started.wait(timeout=1)
        raise RuntimeError("provider stream broke")

    agent._stream_responses_with_retry = fake_stream

    try:
        try:
            agent._send_via_responses(
                messages=[{"role": "user", "content": "run echo"}],
                active_tools=[],
                run_tools=True,
                reasoning_effort="",
            )
        except RuntimeError as exc:
            assert "provider stream broke" in str(exc)
        else:
            raise AssertionError("provider stream failure should propagate")

        notices = _abort_notices(agent)
        assert len(notices) == 1
        assert notices[0]["reason"] == "stream_failed"
        assert notices[0]["responses_mode"] == "item_level"
        assert notices[0]["tool_call_count"] == 1
        assert notices[0]["future_count"] == 1
        assert notices[0]["running_count"] == 1
        assert notices[0]["call_ids"] == ["call-1"]
    finally:
        release_tool.set()


def test_item_level_runtime_reports_cancellation_with_in_flight_tool():
    agent = _openai_agent()
    tool_started = threading.Event()
    release_tool = threading.Event()

    def echo_tool(message=None):
        tool_started.set()
        release_tool.wait(timeout=2)
        return f"echo:{message}"

    agent.tools.function_map["echo_tool"] = echo_tool

    def fake_stream(**kwargs):
        _emit_item_event(kwargs["item_event_handler"])
        assert tool_started.wait(timeout=1)
        raise CancellationRequested("cancelled by test")

    agent._stream_responses_with_retry = fake_stream

    try:
        try:
            agent._send_via_responses(
                messages=[{"role": "user", "content": "run echo"}],
                active_tools=[],
                run_tools=True,
                reasoning_effort="",
            )
        except CancellationRequested as exc:
            assert "cancelled by test" in str(exc)
        else:
            raise AssertionError("cancellation should propagate")

        notices = _abort_notices(agent)
        assert len(notices) == 1
        assert notices[0]["reason"] == "cancelled"
        assert notices[0]["running_count"] == 1
        assert notices[0]["call_ids"] == ["call-1"]
    finally:
        release_tool.set()


def test_item_level_runtime_propagates_worker_resolver_errors():
    agent = _openai_agent()
    agent.tools.function_map["echo_tool"] = lambda message=None: f"echo:{message}"

    def fail_worker_resolution(_task_count):
        raise RuntimeError("worker resolver failed")

    agent._resolve_parallel_workers = fail_worker_resolution

    def fake_stream(**kwargs):
        _emit_item_event(kwargs["item_event_handler"])
        raise AssertionError("worker resolver failure should stop stream handling")

    agent._stream_responses_with_retry = fake_stream

    try:
        agent._send_via_responses(
            messages=[{"role": "user", "content": "run echo"}],
            active_tools=[],
            run_tools=True,
            reasoning_effort="",
        )
    except RuntimeError as exc:
        assert "worker resolver failed" in str(exc)
    else:
        raise AssertionError("worker resolver failure should propagate")

    notices = _abort_notices(agent)
    assert len(notices) == 1
    assert notices[0]["tool_call_count"] == 1
    assert notices[0]["future_count"] == 0
