from __future__ import annotations

import json

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedError
from websockets.exceptions import InvalidStatus
from websockets.frames import Close
from websockets.http11 import Response

from src.providers.openai_agent import OpenAIAgent
from src.providers.openai_transport_errors import OpenAITransportError
from src.providers.responses_websocket_transport import ResponsesWebSocketTransportMixin


class _ScriptedConnection:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []
        self.recv_timeouts = []

    def send(self, message):
        self.sent.append(json.loads(message))

    def recv(self, timeout=None):
        self.recv_timeouts.append(timeout)
        return json.dumps(self.messages.pop(0))

    def close(self):
        return None


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
        self.config = {"responsesWebSocket": True}
        self._responses_ws_connection = _KeepaliveTimeoutConnection(messages)
        self.notices = []
        self.http_calls = 0

    def _emit_provider_runtime_notice(self, *, message, stage):
        self.notices.append((stage, message))

    def _curl_post_sse_data_lines(self, **_kwargs):
        self.http_calls += 1
        yield "http-sse-event"


def _agent():
    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "timeoutMs": 1000,
        "maxRetries": 0,
        "overloadMaxRetries": 1,
        "retryDelaySec": 0,
        "retryJitterRatio": 0,
        "responsesWebSocket": True,
    }
    agent.provider_name = "openai"
    agent.events = []
    agent.tool_event_callback = agent.events.append
    return agent


def test_websocket_transport_can_be_disabled_by_provider_contract():
    agent = _agent()
    agent.config["responsesWebSocket"] = False

    assert agent._responses_websocket_available() is False


def test_websocket_transport_requires_explicit_provider_opt_in():
    agent = _agent()
    agent.config.pop("responsesWebSocket")

    assert agent._responses_websocket_available() is False


def _completed(response_id):
    return {
        "type": "response.completed",
        "response": {
            "id": response_id,
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "recovered"}],
                }
            ],
        },
    }


def _stream(agent, *, headers=None):
    return agent._stream_responses_with_retry(
        endpoint="responses",
        url="https://api.example.test/v1/responses",
        headers=dict(headers or {"Authorization": "Bearer test"}),
        payload_json=json.dumps(
            {
                "model": "gpt-test",
                "input": [],
                "stream": True,
            }
        ),
        stream_handler=None,
    )


def _handshake_error(status_code):
    return InvalidStatus(
        Response(
            status_code,
            "Handshake rejected",
            Headers(),
            body=b'{"error":{"message":"handshake rejected"}}',
        )
    )


def test_websocket_handshake_401_refreshes_auth_and_reconnects(monkeypatch):
    connection = _ScriptedConnection([_completed("resp-recovered")])
    connect_calls = []

    def connect(_url, **kwargs):
        connect_calls.append(dict(kwargs))
        if len(connect_calls) == 1:
            raise _handshake_error(401)
        return connection

    monkeypatch.setattr("websockets.sync.client.connect", connect)
    agent = _agent()
    agent.config["authMode"] = "codex"
    refreshed = []
    agent._reload_responses_auth_headers = lambda _headers: False

    def refresh_headers(headers):
        refreshed.append(dict(headers))
        headers["Authorization"] = "Bearer refreshed"
        return True

    agent._refresh_responses_auth_headers = refresh_headers

    result = _stream(
        agent,
        headers={"Authorization": "Bearer expired"},
    )

    assert result["id"] == "resp-recovered"
    assert refreshed == [{"Authorization": "Bearer expired"}]
    assert len(connect_calls) == 2
    assert connect_calls[1]["additional_headers"]["Authorization"] == "Bearer refreshed"


def test_websocket_handshake_401_reloads_then_refreshes_on_second_401(
    monkeypatch,
):
    connection = _ScriptedConnection([_completed("resp-recovered")])
    connect_calls = []

    def connect(_url, **kwargs):
        connect_calls.append(dict(kwargs))
        if len(connect_calls) <= 2:
            raise _handshake_error(401)
        return connection

    monkeypatch.setattr("websockets.sync.client.connect", connect)
    agent = _agent()
    agent.config["authMode"] = "codex"
    recoveries = []

    def reload_headers(headers):
        recoveries.append("reload")
        headers["Authorization"] = "Bearer reloaded"
        return True

    def refresh_headers(headers):
        recoveries.append("refresh")
        headers["Authorization"] = "Bearer refreshed"
        return True

    agent._reload_responses_auth_headers = reload_headers
    agent._refresh_responses_auth_headers = refresh_headers

    result = _stream(
        agent,
        headers={"Authorization": "Bearer expired"},
    )

    assert result["id"] == "resp-recovered"
    assert recoveries == ["reload", "refresh"]
    assert len(connect_calls) == 3
    assert connect_calls[1]["additional_headers"]["Authorization"] == "Bearer reloaded"
    assert connect_calls[2]["additional_headers"]["Authorization"] == "Bearer refreshed"


@pytest.mark.parametrize("status_code", [404, 405, 426])
def test_unsupported_websocket_handshake_falls_back_to_http(monkeypatch, status_code):
    connect_calls = []
    http_requests = []

    def connect(_url, **kwargs):
        connect_calls.append(dict(kwargs))
        raise _handshake_error(status_code)

    def completed_http_response(**kwargs):
        http_requests.append(json.loads(kwargs["payload_json"]))
        yield json.dumps(_completed("resp-http"))

    monkeypatch.setattr("websockets.sync.client.connect", connect)
    agent = _agent()
    agent._curl_post_sse_data_lines = completed_http_response

    result = _stream(agent)

    assert result["id"] == "resp-http"
    assert len(connect_calls) == 1
    assert len(http_requests) == 1


def test_transient_websocket_handshake_uses_request_budget_and_stream_timeouts(
    monkeypatch,
):
    connection = _ScriptedConnection([_completed("resp-recovered")])
    connect_calls = []

    def connect(_url, **kwargs):
        connect_calls.append(dict(kwargs))
        if len(connect_calls) == 1:
            raise TimeoutError("temporary handshake timeout")
        return connection

    monkeypatch.setattr("websockets.sync.client.connect", connect)
    monkeypatch.setattr(
        "src.providers.openai_retry_transport.sleep_with_cancel",
        lambda _delay, _source: None,
    )
    agent = _agent()
    agent.config.update(
        {
            "requestMaxRetries": 1,
            "streamMaxRetries": 0,
        }
    )

    result = _stream(agent)

    assert result["id"] == "resp-recovered"
    assert len(connect_calls) == 2
    assert connect_calls[0]["open_timeout"] == 15
    assert connection.recv_timeouts == [300]
    request_notices = [
        event
        for event in agent.events
        if event.get("stage") == "openai_responses_request_retry"
    ]
    assert len(request_notices) == 1


def test_websocket_keepalive_before_first_event_is_request_retryable():
    transport = _FallbackRecordingTransport()

    with pytest.raises(
        OpenAITransportError,
        match="before first response event",
    ) as exc_info:
        list(
            transport._responses_stream_data_lines(
                url="https://api.example.test/v1/responses",
                headers={"Authorization": "Bearer test"},
                payload_json=json.dumps(
                    {"model": "gpt-test", "input": [], "stream": True}
                ),
                timeout_sec=60,
            )
        )

    assert exc_info.value.retry_scope == "request"
    assert transport.http_calls == 0
    assert all(
        stage != "openai_responses_websocket_fallback"
        for stage, _message in transport.notices
    )


def test_websocket_keepalive_after_first_event_is_stream_retryable():
    transport = _FallbackRecordingTransport(
        [json.dumps({"type": "response.output_text.delta", "delta": "partial"})]
    )
    stream = transport._responses_stream_data_lines(
        url="https://api.example.test/v1/responses",
        headers={"Authorization": "Bearer test"},
        payload_json=json.dumps(
            {"model": "gpt-test", "input": [], "stream": True}
        ),
        timeout_sec=60,
    )

    assert json.loads(next(stream))["delta"] == "partial"
    with pytest.raises(
        OpenAITransportError,
        match="websocket receive failed",
    ) as exc_info:
        next(stream)
    assert exc_info.value.retry_scope == "stream"
    assert transport.http_calls == 0
    assert all(
        stage != "openai_responses_websocket_fallback"
        for stage, _message in transport.notices
    )
