from __future__ import annotations

import json

import pytest

from src.providers.openai_agent import OpenAIAgent


class _ScriptedConnection:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []

    def send(self, message):
        self.sent.append(json.loads(message))

    def recv(self, timeout=None):
        _ = timeout
        return json.dumps(self.messages.pop(0))


def _agent(connection, *, max_retries):
    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "timeoutMs": 1000,
        "maxRetries": max_retries,
        "overloadMaxRetries": 0,
        "retryDelaySec": 0,
        "retryJitterRatio": 0,
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


def test_websocket_server_error_stops_at_the_general_retry_budget(monkeypatch):
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

    with pytest.raises(RuntimeError, match="temporary failure two"):
        _request(agent)

    assert len(connection.sent) == 2


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
