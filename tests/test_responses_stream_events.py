import json

from src.providers.openai_responses_stream_normalizer import OpenAIResponsesStreamEventNormalizer
from src.providers.responses_stream_events import ResponsesFunctionCallArgumentsDelta
from src.providers.responses_stream_events import ResponsesOutputItemDone
from src.providers.responses_stream_events import ResponsesReasoningDelta
from src.providers.responses_stream_events import ResponsesServerToolActivity
from src.providers.responses_stream_events import ResponsesStreamFailure


def _ingest_events(raw_events):
    normalizer = OpenAIResponsesStreamEventNormalizer()
    events = []
    for raw_event in raw_events:
        events.extend(normalizer.ingest_sse_data(json.dumps(raw_event)))
    return events


def test_openai_responses_sse_events_normalize_to_typed_runtime_events():
    events = _ingest_events(
        [
            {"type": "response.created", "response": {"id": "resp-1"}},
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {"type": "function_call", "id": "fc_item_1", "name": "echo_tool"},
            },
            {
                "type": "response.output_text.delta",
                "item_id": "msg-1",
                "output_index": 1,
                "content_index": 0,
                "delta": "Checking.",
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_item_1",
                "delta": '{"message"',
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_item_1",
                "delta": ':"hello"}',
            },
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "id": "fc_item_1",
                    "call_id": "call_real_1",
                    "name": "echo_tool",
                    "arguments": '{"message":"hello"}',
                    "status": "completed",
                },
            },
            {"type": "response.completed", "response": {"id": "resp-1", "output": []}},
        ]
    )

    assert [event.event for event in events] == [
        "response_created",
        "output_item_added",
        "output_text_delta",
        "function_call_arguments_delta",
        "function_call_arguments_delta",
        "output_item_done",
        "response_completed",
    ]
    assert all(not isinstance(event, dict) for event in events)

    argument_deltas = [event for event in events if isinstance(event, ResponsesFunctionCallArgumentsDelta)]
    assert argument_deltas[-1].arguments == '{"message":"hello"}'

    done_event = next(event for event in events if isinstance(event, ResponsesOutputItemDone))
    assert done_event.function_call is not None
    assert done_event.function_call.id == "fc_item_1"
    assert done_event.function_call.call_id == "call_real_1"
    assert done_event.function_call.name == "echo_tool"
    assert done_event.function_call.arguments == '{"message":"hello"}'
    assert done_event.item == {
        "type": "function_call",
        "id": "fc_item_1",
        "call_id": "call_real_1",
        "name": "echo_tool",
        "arguments": '{"message":"hello"}',
        "status": "completed",
    }


def test_openai_responses_server_tool_status_event_normalizes():
    events = _ingest_events(
        [
            {
                "type": "response.web_search_call.searching",
                "item_id": "ws_1",
                "output_index": 0,
                "action": {"type": "search", "query": "AgentPark"},
            }
        ]
    )

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, ResponsesServerToolActivity)
    assert event.item_type == "web_search_call"
    assert event.status == "in_progress"
    assert event.item["action"] == {"type": "search", "query": "AgentPark"}


def test_openai_responses_sse_malformed_json_surfaces_typed_failure():
    normalizer = OpenAIResponsesStreamEventNormalizer()

    events = normalizer.ingest_sse_data('{"type": "response.created"')

    assert len(events) == 1
    assert isinstance(events[0], ResponsesStreamFailure)
    assert events[0].event == "response_failed"
    assert events[0].code == "invalid_sse_json"
    assert "Malformed Responses SSE event JSON" in events[0].message


def test_openai_responses_sse_reasoning_summary_delta_normalizes():
    events = _ingest_events(
        [
            {
                "type": "response.reasoning_summary_text.delta",
                "item_id": "rs_1",
                "output_index": 0,
                "content_index": 0,
                "delta": "Need a short plan.",
            },
        ]
    )

    assert len(events) == 1
    assert isinstance(events[0], ResponsesReasoningDelta)
    assert events[0].delta == "Need a short plan."
    assert events[0].item_id == "rs_1"
    assert events[0].provider == "openai_responses"


def test_openai_responses_sse_reasoning_summary_part_done_normalizes_when_no_delta_was_sent():
    events = _ingest_events(
        [
            {
                "type": "response.reasoning_summary_part.done",
                "item_id": "rs_1",
                "output_index": 0,
                "summary_index": 0,
                "part": {"type": "summary_text", "text": "Need a short plan."},
            },
        ]
    )

    assert len(events) == 1
    assert isinstance(events[0], ResponsesReasoningDelta)
    assert events[0].delta == "Need a short plan."
    assert events[0].item_id == "rs_1"
    assert events[0].provider == "openai_responses"


def test_openai_responses_sse_reasoning_done_snapshots_do_not_repeat_streamed_delta():
    events = _ingest_events(
        [
            {
                "type": "response.reasoning_summary_text.delta",
                "item_id": "rs_1",
                "output_index": 0,
                "summary_index": 0,
                "delta": "Need a short plan.",
            },
            {
                "type": "response.reasoning_summary_part.done",
                "item_id": "rs_1",
                "output_index": 0,
                "summary_index": 0,
                "part": {"type": "summary_text", "text": "Need a short plan."},
            },
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "item": {
                    "type": "reasoning",
                    "id": "rs_1",
                    "summary": [{"type": "summary_text", "text": "Need a short plan."}],
                },
            },
        ]
    )

    reasoning_events = [event for event in events if isinstance(event, ResponsesReasoningDelta)]
    assert [event.delta for event in reasoning_events] == ["Need a short plan."]
    assert [event.event for event in events] == ["reasoning_delta", "output_item_done"]


def test_openai_responses_sse_reasoning_done_snapshot_emits_only_missing_suffix():
    events = _ingest_events(
        [
            {
                "type": "response.reasoning_summary_text.delta",
                "item_id": "rs_1",
                "summary_index": 0,
                "delta": "Need a ",
            },
            {
                "type": "response.reasoning_summary_part.done",
                "item_id": "rs_1",
                "summary_index": 0,
                "part": {"type": "summary_text", "text": "Need a short plan."},
            },
        ]
    )

    assert [event.delta for event in events if isinstance(event, ResponsesReasoningDelta)] == [
        "Need a ",
        "short plan.",
    ]


def test_openai_responses_sse_rejects_inconsistent_reasoning_done_snapshot():
    events = _ingest_events(
        [
            {
                "type": "response.reasoning_summary_text.delta",
                "item_id": "rs_1",
                "summary_index": 0,
                "delta": "Need a plan.",
            },
            {
                "type": "response.reasoning_summary_part.done",
                "item_id": "rs_1",
                "summary_index": 0,
                "part": {"type": "summary_text", "text": "Use a different plan."},
            },
        ]
    )

    assert isinstance(events[-1], ResponsesStreamFailure)
    assert events[-1].code == "inconsistent_reasoning_snapshot"


def test_function_call_arguments_delta_requires_item_or_call_identity():
    events = _ingest_events(
        [
            {
                "type": "response.function_call_arguments.delta",
                "delta": "{}",
            },
        ]
    )

    assert len(events) == 1
    assert isinstance(events[0], ResponsesStreamFailure)
    assert events[0].code == "missing_function_call_identity"
    assert "missing item_id or call_id" in events[0].message


def test_function_call_output_item_done_requires_complete_call_payload():
    events = _ingest_events(
        [
            {
                "type": "response.output_item.added",
                "item": {"type": "function_call", "id": "fc_item_1", "name": "echo_tool"},
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "id": "fc_item_1",
                    "name": "echo_tool",
                    "arguments": "{}",
                },
            },
        ]
    )

    assert [event.event for event in events] == ["output_item_added", "response_failed"]
    assert isinstance(events[-1], ResponsesStreamFailure)
    assert events[-1].code == "incomplete_function_call"
    assert "call_id" in events[-1].message


def test_function_call_arguments_must_remain_string_payloads():
    events = _ingest_events(
        [
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "id": "fc_item_1",
                    "call_id": "call_real_1",
                    "name": "echo_tool",
                    "arguments": {"message": "hello"},
                },
            },
        ]
    )

    assert len(events) == 1
    assert isinstance(events[0], ResponsesStreamFailure)
    assert events[0].code == "invalid_function_call_arguments"
    assert "requires string arguments" in events[0].message


def test_openai_transport_collects_normalized_events_from_mocked_sse(monkeypatch):
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {"timeoutMs": 1000}
    agent.provider_name = "openai"
    raw_events = [
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
    monkeypatch.setattr(agent, "_curl_post_sse_data_lines", lambda **_kwargs: (json.dumps(event) for event in raw_events))
    collected = []

    result = agent._stream_responses_once(
        url="https://api.openai.test/v1/responses",
        headers={},
        payload_json="{}",
        timeout_sec=1,
        stream_handler=None,
        item_event_handler=collected.append,
    )

    assert [event.event for event in collected] == [
        "output_item_added",
        "function_call_arguments_delta",
        "output_item_done",
    ]
    assert all(not isinstance(event, dict) for event in collected)
    assert result["output"][0] == {
        "type": "function_call",
        "id": "fc_item_1",
        "call_id": "call_real_1",
        "name": "echo_tool",
        "arguments": '{"message":"hello"}',
    }


def test_openai_transport_text_streaming_stays_delta_then_full(monkeypatch):
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {"timeoutMs": 1000}
    agent.provider_name = "openai"
    raw_events = [
        {"type": "response.output_text.delta", "delta": "he"},
        {"type": "response.output_text.delta", "delta": "llo"},
        {
            "type": "response.completed",
            "response": {
                "id": "resp-1",
                "output": [
                    {"type": "message", "content": [{"type": "output_text", "text": "hello"}]},
                ],
            },
        },
    ]
    monkeypatch.setattr(agent, "_curl_post_sse_data_lines", lambda **_kwargs: (json.dumps(event) for event in raw_events))
    stream_events = []
    collected = []

    result = agent._stream_responses_once(
        url="https://api.openai.test/v1/responses",
        headers={},
        payload_json="{}",
        timeout_sec=1,
        stream_handler=lambda delta, full: stream_events.append((delta, full)),
        item_event_handler=collected.append,
    )

    assert stream_events == [("he", "he"), ("llo", "hello")]
    assert [event.event for event in collected] == [
        "output_text_delta",
        "output_text_delta",
        "response_completed",
    ]
    assert result["output"][0]["content"][0]["text"] == "hello"


def test_openai_transport_forwards_reasoning_delta_to_thinking_stream(monkeypatch):
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {"timeoutMs": 1000}
    agent.provider_name = "openai"
    raw_events = [
        {"type": "response.reasoning_summary_text.delta", "delta": "plan"},
        {"type": "response.output_text.delta", "delta": "done"},
    ]
    monkeypatch.setattr(agent, "_curl_post_sse_data_lines", lambda **_kwargs: (json.dumps(event) for event in raw_events))
    stream_events = []
    thinking_events = []

    result = agent._stream_responses_once(
        url="https://api.openai.test/v1/responses",
        headers={},
        payload_json="{}",
        timeout_sec=1,
        stream_handler=lambda delta, full: stream_events.append((delta, full)),
        thinking_stream_handler=lambda delta, full, provider: thinking_events.append((delta, full, provider)),
    )

    assert stream_events == [("done", "done")]
    assert thinking_events == [("plan", "plan", "openai_responses")]
    assert result["output"][0]["content"][0]["text"] == "done"


def test_openai_transport_returns_immediately_after_response_completed(monkeypatch):
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {"timeoutMs": 1000}
    agent.provider_name = "openai"
    agent_events = []
    agent.tool_event_callback = agent_events.append
    consumed = []

    def fake_sse_lines(**_kwargs):
        events = [
            {"type": "response.output_text.delta", "delta": "he"},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-1",
                    "output": [
                        {"type": "message", "content": [{"type": "output_text", "text": "hello"}]},
                    ],
                },
            },
            {"type": "response.output_text.delta", "delta": "late"},
        ]
        for event in events:
            consumed.append(event["type"])
            yield json.dumps(event)

    monkeypatch.setattr(agent, "_curl_post_sse_data_lines", fake_sse_lines)
    stream_events = []

    result = agent._stream_responses_once(
        url="https://api.openai.test/v1/responses",
        headers={},
        payload_json="{}",
        timeout_sec=1,
        stream_handler=lambda delta, full: stream_events.append((delta, full)),
        item_event_handler=None,
    )

    assert consumed == ["response.output_text.delta", "response.completed"]
    assert stream_events == [("he", "he"), ("llo", "hello")]
    assert result["output"][0]["content"][0]["text"] == "hello"
    notices = [
        event
        for event in agent_events
        if event.get("type") == "runtime_notice"
        and event.get("stage") == "openai_responses_completed_break"
    ]
    assert len(notices) == 1
    payload = json.loads(notices[0]["message"])
    assert payload["event"] == "response.completed"
    assert payload["response_id"] == "resp-1"
    assert payload["break_after_completed"] is True
    assert payload["stream_text_chars"] == 2


def test_openai_transport_logs_function_call_item_done_before_completed_break(monkeypatch):
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {"timeoutMs": 1000}
    agent.provider_name = "openai"
    agent_events = []
    agent.tool_event_callback = agent_events.append
    consumed = []

    def fake_sse_lines(**_kwargs):
        events = [
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "id": "fc-item-1",
                    "call_id": "call-real-1",
                    "name": "echo_tool",
                    "arguments": '{"message":"hello"}',
                    "status": "completed",
                },
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-1",
                    "output": [
                        {
                            "type": "function_call",
                            "id": "fc-item-1",
                            "call_id": "call-real-1",
                            "name": "echo_tool",
                            "arguments": '{"message":"hello"}',
                        }
                    ],
                },
            },
            {"type": "response.output_text.delta", "delta": "late"},
        ]
        for event in events:
            consumed.append(event["type"])
            yield json.dumps(event)

    monkeypatch.setattr(agent, "_curl_post_sse_data_lines", fake_sse_lines)

    result = agent._stream_responses_once(
        url="https://api.openai.test/v1/responses",
        headers={},
        payload_json="{}",
        timeout_sec=1,
        stream_handler=None,
        item_event_handler=None,
    )

    assert consumed == ["response.output_item.done", "response.completed"]
    assert result["output"][0]["call_id"] == "call-real-1"
    notices_by_stage = {
        event.get("stage"): json.loads(event["message"])
        for event in agent_events
        if event.get("type") == "runtime_notice"
    }
    item_done = notices_by_stage["openai_responses_function_call_item_done"]
    assert item_done["event"] == "response.output_item.done"
    assert item_done["call_id"] == "call-real-1"
    assert item_done["function_call_items_seen"] == 1
    completed = notices_by_stage["openai_responses_completed_break"]
    assert completed["event"] == "response.completed"
    assert completed["response_id"] == "resp-1"
    assert completed["break_after_completed"] is True
    assert completed["completed_function_call_count"] == 1
    assert completed["stream_function_call_item_count"] == 1


def test_openai_transport_merges_done_items_when_completed_output_is_empty(monkeypatch):
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {"timeoutMs": 1000}
    agent.provider_name = "openai"
    reasoning = {
        "type": "reasoning",
        "id": "rs-item-1",
        "encrypted_content": "encrypted",
        "summary": [],
    }
    function_call = {
        "type": "function_call",
        "id": "fc-item-1",
        "call_id": "call-real-1",
        "name": "echo_tool",
        "arguments": "{}",
        "status": "completed",
    }
    message = {
        "type": "message",
        "id": "msg-item-1",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "checking"}],
        "status": "completed",
    }
    raw_events = [
        {"type": "response.output_item.done", "item": reasoning},
        {"type": "response.output_item.done", "item": message},
        {"type": "response.output_item.done", "item": function_call},
        {"type": "response.completed", "response": {"id": "resp-1", "output": []}},
    ]
    monkeypatch.setattr(
        agent,
        "_curl_post_sse_data_lines",
        lambda **_kwargs: (json.dumps(event) for event in raw_events),
    )

    result = agent._stream_responses_once(
        url="https://api.openai.test/v1/responses",
        headers={},
        payload_json="{}",
        timeout_sec=1,
        stream_handler=None,
        item_event_handler=None,
    )

    assert result["id"] == "resp-1"
    assert result["output"] == [reasoning, message, function_call]
