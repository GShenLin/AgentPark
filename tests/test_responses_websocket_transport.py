import json

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from src.providers.openai_transport_errors import OpenAITransportError
from src.providers.responses_websocket_transport import incremental_request_input
from src.providers.responses_websocket_transport import responses_websocket_url
from src.providers.responses_websocket_transport import websocket_error_message
from src.providers.responses_websocket_transport import websocket_response_create_payload
from src.providers.responses_websocket_transport import ResponsesWebSocketTransportMixin


class _KeepaliveTimeoutConnection:
    def __init__(self, messages=()):
        self.messages = list(messages)

    def send(self, _message):
        return None

    def recv(self, timeout=None):
        _ = timeout
        if self.messages:
            return self.messages.pop(0)
        raise ConnectionClosedError(None, Close(1011, "keepalive ping timeout"))

    def close(self):
        return None


class _FallbackRecordingTransport(ResponsesWebSocketTransportMixin):
    def __init__(self, messages=()):
        self._responses_ws_connection = _KeepaliveTimeoutConnection(messages)
        self.notices = []
        self.http_calls = 0

    def _emit_provider_runtime_notice(self, *, message, stage):
        self.notices.append((stage, message))

    def _curl_post_sse_data_lines(self, **_kwargs):
        self.http_calls += 1
        yield "http-sse-event"


def test_responses_websocket_url_converts_http_scheme_only():
    assert responses_websocket_url("https://api.example.test/v1/responses") == "wss://api.example.test/v1/responses"
    assert responses_websocket_url("http://127.0.0.1:8080/v1/responses") == "ws://127.0.0.1:8080/v1/responses"


def test_responses_websocket_headers_add_codex_beta_without_mutating_input():
    headers = {"Authorization": "Bearer test"}

    ws_headers = ResponsesWebSocketTransportMixin._responses_websocket_headers(headers)

    assert headers == {"Authorization": "Bearer test"}
    assert ws_headers["Authorization"] == "Bearer test"
    assert ws_headers["OpenAI-Beta"] == "responses_websockets=2026-02-06"


def test_websocket_error_message_preserves_structured_provider_code():
    error = websocket_error_message(
        {
            "type": "error",
            "error": {
                "code": "server_error",
                "message": "temporary failure",
            },
        }
    )

    assert error == (
        0,
        "server_error",
        "server_error: temporary failure",
    )


def test_websocket_payload_uses_previous_response_id_only_for_strict_extension():
    previous_request = {
        "model": "gpt-test",
        "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "run"}]}],
        "tools": [{"type": "function", "name": "echo", "parameters": {"type": "object"}}],
        "stream": True,
    }
    previous_response = {
        "id": "resp-1",
        "output": [
            {
                "type": "function_call",
                "id": "fc-1",
                "call_id": "call-1",
                "name": "echo",
                "arguments": "{}",
                "status": "completed",
            }
        ],
    }
    current_request = {
        **previous_request,
        "input": [
            *previous_request["input"],
            *previous_response["output"],
            {"type": "function_call_output", "call_id": "call-1", "output": "ok", "status": "completed"},
        ],
    }

    ws_payload, incremental = websocket_response_create_payload(
        request_payload=current_request,
        previous_request_payload=previous_request,
        previous_response=previous_response,
    )

    assert incremental is True
    assert ws_payload["type"] == "response.create"
    assert ws_payload["previous_response_id"] == "resp-1"
    assert ws_payload["input"] == [
        {"type": "function_call_output", "call_id": "call-1", "output": "ok", "status": "completed"}
    ]


def test_websocket_payload_allows_local_history_to_omit_server_reasoning_item():
    previous_input = [{"type": "message", "role": "user", "content": []}]
    reasoning = {
        "type": "reasoning",
        "id": "rs-1",
        "encrypted_content": "encrypted",
        "summary": [],
    }
    function_call = {
        "type": "function_call",
        "id": "fc-1",
        "call_id": "call-1",
        "name": "echo",
        "arguments": "{}",
        "status": "completed",
    }
    previous_request = {"model": "gpt-test", "input": previous_input, "stream": True}
    previous_response = {"id": "resp-1", "output": [reasoning, function_call]}
    current_request = {
        **previous_request,
        "input": [
            *previous_input,
            function_call,
            {"type": "function_call_output", "call_id": "call-1", "output": "ok", "status": "completed"},
        ],
    }

    ws_payload, incremental = websocket_response_create_payload(
        request_payload=current_request,
        previous_request_payload=previous_request,
        previous_response=previous_response,
    )

    assert incremental is True
    assert ws_payload["previous_response_id"] == "resp-1"
    assert ws_payload["input"] == [
        {"type": "function_call_output", "call_id": "call-1", "output": "ok", "status": "completed"}
    ]


def test_websocket_payload_matches_normalized_assistant_message_with_reasoning():
    previous_input = [{"type": "message", "role": "user", "content": []}]
    reasoning = {
        "type": "reasoning",
        "id": "rs-1",
        "encrypted_content": "encrypted",
        "summary": [],
    }
    message_output = {
        "type": "message",
        "id": "msg-1",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "checking"}],
        "status": "completed",
    }
    normalized_message = {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "checking"}],
        "status": "completed",
    }
    function_call = {
        "type": "function_call",
        "id": "fc-1",
        "call_id": "call-1",
        "name": "echo",
        "arguments": "{}",
        "status": "completed",
    }
    previous_request = {"model": "gpt-test", "input": previous_input, "stream": True}
    previous_response = {"id": "resp-1", "output": [reasoning, message_output, function_call]}
    current_request = {
        **previous_request,
        "input": [
            *previous_input,
            reasoning,
            normalized_message,
            function_call,
            {"type": "function_call_output", "call_id": "call-1", "output": "ok", "status": "completed"},
        ],
    }

    ws_payload, incremental = websocket_response_create_payload(
        request_payload=current_request,
        previous_request_payload=previous_request,
        previous_response=previous_response,
    )

    assert incremental is True
    assert ws_payload["previous_response_id"] == "resp-1"
    assert ws_payload["input"] == [
        {"type": "function_call_output", "call_id": "call-1", "output": "ok", "status": "completed"}
    ]


def test_websocket_payload_falls_back_to_full_input_when_properties_change():
    previous_request = {"model": "gpt-test", "input": [{"type": "message", "role": "user", "content": []}], "stream": True}
    previous_response = {"id": "resp-1", "output": []}
    current_request = {"model": "gpt-other", "input": list(previous_request["input"]), "stream": True}

    assert incremental_request_input(
        current_request=current_request,
        previous_request=previous_request,
        previous_response=previous_response,
    ) is None
    ws_payload, incremental = websocket_response_create_payload(
        request_payload=current_request,
        previous_request_payload=previous_request,
        previous_response=previous_response,
    )

    assert incremental is False
    assert "previous_response_id" not in ws_payload
    assert ws_payload["input"] == current_request["input"]


def test_openai_transport_sends_incremental_payload_over_websocket():
    import json

    from src.providers.openai_agent import OpenAIAgent

    class FakeConnection:
        def __init__(self, messages):
            self.messages = list(messages)
            self.sent = []

        def send(self, message):
            self.sent.append(json.loads(message))

        def recv(self, timeout=None):
            _ = timeout
            return json.dumps(self.messages.pop(0))

    first_input = [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "run echo"}]}]
    function_call = {
        "type": "function_call",
        "id": "fc-1",
        "call_id": "call-1",
        "name": "echo",
        "arguments": "{}",
        "status": "completed",
    }
    fake = FakeConnection(
        [
            {"type": "response.output_item.done", "item": function_call},
            {"type": "response.completed", "response": {"id": "resp-1", "output": []}},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-2",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "done"}]}],
                },
            },
        ]
    )
    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {"timeoutMs": 1000, "maxRetries": 0, "retryDelaySec": 0}
    agent.provider_name = "openai"
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent._responses_websocket_connection = lambda **_kwargs: fake

    first_payload = {"model": "gpt-test", "input": first_input, "stream": True}
    agent._stream_responses_with_retry(
        endpoint="responses",
        url="https://api.example.test/v1/responses",
        headers={"Authorization": "Bearer test"},
        payload_json=json.dumps(first_payload),
        stream_handler=None,
    )
    second_payload = {
        **first_payload,
        "input": [
            *first_input,
            function_call,
            {"type": "function_call_output", "call_id": "call-1", "output": "ok", "status": "completed"},
        ],
    }
    agent._stream_responses_with_retry(
        endpoint="responses",
        url="https://api.example.test/v1/responses",
        headers={"Authorization": "Bearer test"},
        payload_json=json.dumps(second_payload),
        stream_handler=None,
    )

    assert fake.sent[0]["type"] == "response.create"
    assert "previous_response_id" not in fake.sent[0]
    assert fake.sent[0]["input"] == first_input
    assert fake.sent[1]["previous_response_id"] == "resp-1"
    assert fake.sent[1]["input"] == [
        {"type": "function_call_output", "call_id": "call-1", "output": "ok", "status": "completed"}
    ]


def test_websocket_streamed_and_completed_output_items_are_deduplicated():
    import json

    from src.providers.openai_agent import OpenAIAgent

    class FakeConnection:
        def __init__(self, messages):
            self.messages = list(messages)
            self.sent = []

        def send(self, message):
            self.sent.append(json.loads(message))

        def recv(self, timeout=None):
            _ = timeout
            return json.dumps(self.messages.pop(0))

    reasoning = {
        "type": "reasoning",
        "id": "rs-1",
        "encrypted_content": "encrypted",
        "summary": [],
    }
    function_call = {
        "type": "function_call",
        "id": "fc-1",
        "call_id": "call-1",
        "name": "echo",
        "arguments": "{}",
        "status": "completed",
    }
    fake = FakeConnection(
        [
            {"type": "response.output_item.done", "item": reasoning},
            {"type": "response.output_item.done", "item": function_call},
            {"type": "response.completed", "response": {"id": "resp-1", "output": [function_call]}},
        ]
    )
    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {"timeoutMs": 1000, "maxRetries": 0, "retryDelaySec": 0}
    agent.provider_name = "openai"
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent._responses_websocket_connection = lambda **_kwargs: fake

    agent._stream_responses_with_retry(
        endpoint="responses",
        url="https://api.example.test/v1/responses",
        headers={"Authorization": "Bearer test"},
        payload_json=json.dumps({"model": "gpt-test", "input": [], "stream": True}),
        stream_handler=None,
    )

    assert agent._responses_ws_last_response["output"] == [reasoning, function_call]


def test_websocket_keepalive_timeout_before_first_event_falls_back_to_http_sse_once():
    transport = _FallbackRecordingTransport()

    events = list(
        transport._responses_stream_data_lines(
            url="https://api.example.test/v1/responses",
            headers={"Authorization": "Bearer test"},
            payload_json=json.dumps({"model": "gpt-test", "input": [], "stream": True}),
            timeout_sec=60,
        )
    )

    assert events == ["http-sse-event"]
    assert transport.http_calls == 1
    assert transport.notices[-1][0] == "openai_responses_websocket_fallback"
    fallback_notice = json.loads(transport.notices[-1][1])
    assert fallback_notice["fallback"] == "responses_http_sse"
    assert "before first response event" in fallback_notice["reason"]


def test_websocket_keepalive_timeout_after_first_event_does_not_fall_back_to_http_sse():
    transport = _FallbackRecordingTransport(
        [json.dumps({"type": "response.output_text.delta", "delta": "partial"})]
    )
    stream = transport._responses_stream_data_lines(
        url="https://api.example.test/v1/responses",
        headers={"Authorization": "Bearer test"},
        payload_json=json.dumps({"model": "gpt-test", "input": [], "stream": True}),
        timeout_sec=60,
    )

    assert json.loads(next(stream))["delta"] == "partial"
    with pytest.raises(OpenAITransportError, match="websocket receive failed"):
        next(stream)
    assert transport.http_calls == 0
    assert all(stage != "openai_responses_websocket_fallback" for stage, _message in transport.notices)
