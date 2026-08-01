from __future__ import annotations

from src.providers.openai_agent import OpenAIAgent
from src.providers.openai_retry_policy import OpenAIRetryPolicy
from src.providers.openai_retry_policy import OpenAITransportTimeouts
from src.providers.openai_transport_errors import OpenAITransportError


def _agent(config):
    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = dict(config)
    agent.provider_name = "openai"
    agent.events = []
    agent.tool_event_callback = agent.events.append
    return agent


def _completed_response(text="ok"):
    return {
        "id": "resp-ok",
        "output": [
            {"type": "message", "content": [{"type": "output_text", "text": text}]}
        ],
    }


def test_retry_policy_has_independent_request_and_stream_defaults():
    policy = OpenAIRetryPolicy.from_config({})

    assert policy.request_max_retries == 4
    assert policy.stream_max_retries == 5

    explicit = OpenAIRetryPolicy.from_config(
        {
            "requestMaxRetries": 2,
            "streamMaxRetries": 7,
        }
    )

    assert explicit.request_max_retries == 2
    assert explicit.stream_max_retries == 7


def test_transport_timeouts_separate_request_stream_idle_and_websocket_connect():
    defaults = OpenAITransportTimeouts.from_config({})

    assert defaults.request_seconds == 60
    assert defaults.stream_idle_seconds == 300
    assert defaults.websocket_connect_seconds == 15

    configured = OpenAITransportTimeouts.from_config(
        {
            "timeoutMs": 1_000,
            "streamIdleTimeoutMs": 2_000,
            "websocketConnectTimeoutMs": 3_000,
        }
    )

    assert configured.request_seconds == 1
    assert configured.stream_idle_seconds == 2
    assert configured.websocket_connect_seconds == 3


def test_stream_request_and_stream_failures_use_independent_budgets(monkeypatch):
    agent = _agent(
        {
            "timeoutMs": 1000,
            "requestMaxRetries": 1,
            "streamMaxRetries": 1,
            "retryDelaySec": 0,
            "retryJitterRatio": 0,
        }
    )
    calls = {"count": 0}

    def stream_once(**_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OpenAITransportError(
                "request establishment failed",
                retry_scope="request",
            )
        if calls["count"] == 2:
            raise OpenAITransportError(
                "stream disconnected",
                retry_scope="stream",
            )
        return _completed_response()

    monkeypatch.setattr(agent, "_stream_responses_once", stream_once)
    monkeypatch.setattr(
        "src.providers.openai_retry_transport.sleep_with_cancel",
        lambda _delay, _source: None,
    )

    result = agent._stream_responses_with_retry(
        endpoint="responses",
        url="https://api.openai.test/v1/responses",
        headers={},
        payload_json="{}",
        stream_handler=None,
    )

    assert calls["count"] == 3
    assert result["output"][0]["content"][0]["text"] == "ok"
    assert [
        event["stage"]
        for event in agent.events
        if event.get("stage", "").endswith("retry")
    ] == [
        "openai_responses_request_retry",
        "openai_responses_retry",
    ]
