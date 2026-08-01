from __future__ import annotations

import json

import pytest

from src.providers.openai_agent import OpenAIAgent


class _ScriptedConnection:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []
        self.close_count = 0

    def send(self, message):
        self.sent.append(json.loads(message))

    def recv(self, timeout=None):
        _ = timeout
        return json.dumps(self.messages.pop(0))

    def close(self):
        self.close_count += 1


def _agent(connection, *, max_retries):
    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "timeoutMs": 1000,
        "maxRetries": max_retries,
        "overloadMaxRetries": 0,
        "retryDelaySec": 0,
        "retryJitterRatio": 0,
        "responsesWebSocket": True,
    }
    agent.provider_name = "openai"
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent._responses_websocket_connection = lambda **_kwargs: connection
    return agent


def _request(agent):
    return agent._stream_responses_with_retry(
        endpoint="responses",
        url="https://api.example.test/v1/responses",
        headers={"Authorization": "Bearer test"},
        payload_json=json.dumps(
            {
                "model": "gpt-test",
                "input": [],
                "stream": True,
            }
        ),
        stream_handler=None,
    )


def test_websocket_server_error_recovers_with_the_same_logical_request(
    monkeypatch,
):
    connection = _ScriptedConnection(
        [
            {
                "type": "error",
                "error": {
                    "code": "server_error",
                    "message": "An error occurred while processing your request.",
                },
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-recovered",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "recovered",
                                }
                            ],
                        }
                    ],
                },
            },
        ]
    )
    agent = _agent(connection, max_retries=1)
    delays = []
    monkeypatch.setattr(
        "src.providers.openai_retry_transport.sleep_with_cancel",
        lambda delay, _source: delays.append(delay),
    )

    result = _request(agent)

    assert len(connection.sent) == 2
    assert connection.sent[0] == connection.sent[1]
    assert delays == [0.0]
    assert result["id"] == "resp-recovered"
    notices = [
        event
        for event in agent.events
        if event.get("stage") == "openai_responses_retry"
    ]
    assert len(notices) == 1
    assert "Attempt 1/1" in notices[0]["message"]


@pytest.mark.parametrize(
    "provider_code",
    [
        "previous_response_not_found",
        "websocket_connection_limit_reached",
    ],
)
def test_recoverable_websocket_state_error_replays_full_request_without_stale_id(
    monkeypatch,
    provider_code,
):
    connection = _ScriptedConnection(
        [
            {
                "type": "error",
                "status": 400,
                "error": {
                    "code": provider_code,
                    "message": "WebSocket continuation state is unavailable.",
                },
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-recovered",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "recovered",
                                }
                            ],
                        }
                    ],
                },
            },
        ]
    )
    agent = _agent(connection, max_retries=1)
    initial_item = {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "start"}],
    }
    continuation_item = {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "continue"}],
    }
    logical_request = {
        "model": "gpt-test",
        "input": [initial_item, continuation_item],
        "stream": True,
    }
    transport = agent._iter_service_targets()[0]
    transport._responses_ws_last_request_payload = {
        "model": "gpt-test",
        "input": [initial_item],
        "stream": True,
    }
    transport._responses_ws_last_response = {
        "id": "resp-stale",
        "output": [],
    }
    monkeypatch.setattr(
        "src.providers.openai_retry_transport.sleep_with_cancel",
        lambda _delay, _source: None,
    )

    result = agent._stream_responses_with_retry(
        endpoint="responses",
        url="https://api.example.test/v1/responses",
        headers={"Authorization": "Bearer test"},
        payload_json=json.dumps(logical_request),
        stream_handler=None,
    )

    assert connection.sent[0]["previous_response_id"] == "resp-stale"
    assert connection.sent[0]["input"] == [continuation_item]
    assert "previous_response_id" not in connection.sent[1]
    assert connection.sent[1]["input"] == logical_request["input"]
    assert result["id"] == "resp-recovered"
    notices = [
        event
        for event in agent.events
        if event.get("stage") == "openai_responses_retry"
    ]
    assert len(notices) == 1
    assert provider_code in notices[0]["message"]


def test_websocket_server_error_falls_back_to_http_after_retry_budget(
    monkeypatch,
):
    connection = _ScriptedConnection(
        [
            {
                "type": "error",
                "error": {
                    "code": "server_error",
                    "message": "temporary failure one",
                },
            },
            {
                "type": "error",
                "error": {
                    "code": "server_error",
                    "message": "temporary failure two",
                },
            },
        ]
    )
    agent = _agent(connection, max_retries=1)
    monkeypatch.setattr(
        "src.providers.openai_retry_transport.sleep_with_cancel",
        lambda _delay, _source: None,
    )
    http_requests = []

    def scripted_http_response(**kwargs):
        http_requests.append(json.loads(kwargs["payload_json"]))
        if len(http_requests) == 1:
            yield json.dumps(
                {
                    "type": "response.failed",
                    "response": {
                        "error": {
                            "code": "server_error",
                            "message": "temporary HTTP failure",
                        }
                    },
                }
            )
            return
        yield json.dumps(
            {
                "type": "response.completed",
                "response": {
                    "id": "resp-http",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "http recovered",
                                }
                            ],
                        }
                    ],
                },
            }
        )

    monkeypatch.setattr(agent, "_curl_post_sse_data_lines", scripted_http_response)

    result = _request(agent)

    assert len(connection.sent) == 2
    assert len(http_requests) == 2
    assert result["id"] == "resp-http"
    fallback_notices = [
        event
        for event in agent.events
        if event.get("stage") == "openai_responses_websocket_fallback"
    ]
    assert len(fallback_notices) == 1
    fallback_payload = json.loads(fallback_notices[0]["message"])
    assert fallback_payload["fallback"] == "responses_http_sse"
    assert fallback_payload["scope"] == "session"


def test_websocket_non_transient_structured_error_is_not_retried():
    connection = _ScriptedConnection(
        [
            {
                "type": "error",
                "error": {
                    "code": "invalid_request_error",
                    "message": "request shape is invalid",
                },
            }
        ]
    )
    agent = _agent(connection, max_retries=3)

    with pytest.raises(RuntimeError, match="request shape is invalid"):
        _request(agent)

    assert len(connection.sent) == 1
