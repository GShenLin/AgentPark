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

    def close(self):
        return None


def _agent(connection, *, max_retries=1):
    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = {
        "timeoutMs": 1000,
        "maxRetries": max_retries,
        "overloadMaxRetries": 1,
        "retryDelaySec": 0,
        "retryJitterRatio": 0,
        "responsesWebSocket": True,
    }
    agent.provider_name = "openai"
    agent.events = []
    agent.tool_event_callback = agent.events.append
    agent._responses_websocket_connection = lambda **_kwargs: connection
    return agent


def _stream(agent, *, headers=None, input_items=None):
    return agent._stream_responses_with_retry(
        endpoint="responses",
        url="https://api.example.test/v1/responses",
        headers=dict(headers or {"Authorization": "Bearer test"}),
        payload_json=json.dumps(
            {
                "model": "gpt-test",
                "input": list(input_items or []),
                "stream": True,
            }
        ),
        stream_handler=None,
    )


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


def _seed_incremental_state(agent, initial_item):
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


def test_response_incomplete_retries_with_full_request(monkeypatch):
    connection = _ScriptedConnection(
        [
            {
                "type": "response.incomplete",
                "response": {
                    "id": "resp-incomplete",
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [],
                },
            },
            _completed("resp-recovered"),
        ]
    )
    agent = _agent(connection)
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
    _seed_incremental_state(agent, initial_item)
    monkeypatch.setattr(
        "src.providers.openai_retry_transport.sleep_with_cancel",
        lambda _delay, _source: None,
    )

    result = _stream(agent, input_items=[initial_item, continuation_item])

    assert connection.sent[0]["previous_response_id"] == "resp-stale"
    assert connection.sent[0]["input"] == [continuation_item]
    assert "previous_response_id" not in connection.sent[1]
    assert connection.sent[1]["input"] == [initial_item, continuation_item]
    assert result["id"] == "resp-recovered"


def test_unknown_structured_response_failure_is_bounded_retryable(monkeypatch):
    connection = _ScriptedConnection(
        [
            {
                "type": "response.failed",
                "response": {
                    "error": {
                        "code": "new_transient_server_condition",
                        "message": "temporary provider failure",
                    }
                },
            },
            _completed("resp-recovered"),
        ]
    )
    agent = _agent(connection)
    monkeypatch.setattr(
        "src.providers.openai_retry_transport.sleep_with_cancel",
        lambda _delay, _source: None,
    )

    result = _stream(agent)

    assert len(connection.sent) == 2
    assert result["id"] == "resp-recovered"


@pytest.mark.parametrize(
    "provider_code",
    [
        "bio_policy",
        "context_length_exceeded",
        "cyber_policy",
        "insufficient_quota",
        "invalid_prompt",
        "usage_not_included",
    ],
)
def test_known_fatal_structured_response_failure_is_not_retried(provider_code):
    connection = _ScriptedConnection(
        [
            {
                "type": "response.failed",
                "response": {
                    "error": {
                        "status_code": 503,
                        "code": provider_code,
                        "message": "fatal provider failure",
                    }
                },
            }
        ]
    )
    agent = _agent(connection, max_retries=3)

    with pytest.raises(RuntimeError, match=provider_code):
        _stream(agent)

    assert len(connection.sent) == 1


def test_websocket_upgrade_required_falls_back_to_http_without_retry(monkeypatch):
    connection = _ScriptedConnection(
        [
            {
                "type": "error",
                "status": 426,
                "error": {
                    "code": "upgrade_required",
                    "message": "use HTTPS transport",
                },
            }
        ]
    )
    agent = _agent(connection, max_retries=0)
    http_requests = []

    def completed_http_response(**kwargs):
        http_requests.append(json.loads(kwargs["payload_json"]))
        yield json.dumps(_completed("resp-http"))

    monkeypatch.setattr(agent, "_curl_post_sse_data_lines", completed_http_response)

    result = _stream(agent)

    assert len(connection.sent) == 1
    assert len(http_requests) == 1
    assert result["id"] == "resp-http"


def test_websocket_unauthorized_refreshes_auth_and_replays_full_request():
    connection = _ScriptedConnection(
        [
            {
                "type": "response.failed",
                "response": {
                    "error": {
                        "status_code": 401,
                        "code": "invalid_authentication",
                        "message": "access token expired",
                    }
                },
            },
            _completed("resp-recovered"),
        ]
    )
    agent = _agent(connection, max_retries=0)
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
    _seed_incremental_state(agent, initial_item)
    refreshed = []

    def refresh_headers(headers):
        refreshed.append(dict(headers))
        headers["Authorization"] = "Bearer refreshed"
        return True

    agent._refresh_responses_auth_headers = refresh_headers

    result = _stream(
        agent,
        headers={"Authorization": "Bearer expired"},
        input_items=[initial_item, continuation_item],
    )

    assert refreshed == [{"Authorization": "Bearer expired"}]
    assert connection.sent[0]["previous_response_id"] == "resp-stale"
    assert "previous_response_id" not in connection.sent[1]
    assert connection.sent[1]["input"] == [initial_item, continuation_item]
    assert result["id"] == "resp-recovered"
