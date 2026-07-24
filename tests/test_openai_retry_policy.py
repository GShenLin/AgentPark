from __future__ import annotations

import json

import pytest

from src.providers.openai_retry_policy import OpenAIRetryPolicy
from src.providers.openai_retry_policy import OpenAIRetryState
from src.providers.openai_retry_policy import is_retryable_provider_code
from src.providers.openai_retry_policy import parse_retry_after_seconds
from src.providers.openai_transport_errors import OpenAIHttpError
from src.providers.provider_errors import ProviderConfigError


def _agent(config):
    from src.providers.openai_agent import OpenAIAgent

    agent = OpenAIAgent.__new__(OpenAIAgent)
    agent.config = dict(config)
    agent.provider_name = "openai"
    agent.events = []
    agent.tool_event_callback = agent.events.append
    return agent


def _completed_event(text="ok"):
    return {
        "type": "response.completed",
        "response": {
            "id": "resp-ok",
            "output": [
                {"type": "message", "content": [{"type": "output_text", "text": text}]}
            ],
        },
    }


def test_retry_policy_separates_overload_budget_and_exponential_delay():
    policy = OpenAIRetryPolicy.from_config(
        {
            "maxRetries": 2,
            "overloadMaxRetries": 8,
            "retryDelaySec": 1,
            "retryMaxDelaySec": 3,
            "retryJitterRatio": 0.1,
        }
    )

    assert policy.retry_limit(provider_code="service_unavailable") == 2
    assert policy.retry_limit(provider_code="server_is_overloaded") == 8
    assert [
        policy.delay_seconds(attempt=attempt, error_text="", jitter=1.0)
        for attempt in range(1, 5)
    ] == [1.0, 2.0, 3.0, 3.0]
    assert policy.delay_seconds(attempt=4, error_text="", jitter=1.1) == 3.0


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Please try again in 28ms.", 0.028),
        ("Please try again in 1.898s.", 1.898),
        ("Rate limit exceeded. Try again in 35 seconds.", 35.0),
        ("busy", None),
    ],
)
def test_parse_retry_after_seconds_matches_provider_messages(message, expected):
    assert parse_retry_after_seconds(message) == expected


def test_retry_policy_rejects_invalid_explicit_config_instead_of_masking_it():
    with pytest.raises(ProviderConfigError, match="maxRetries must be an integer"):
        OpenAIRetryPolicy.from_config({"maxRetries": "8"})
    with pytest.raises(ProviderConfigError, match="retryJitterRatio must be between"):
        OpenAIRetryPolicy.from_config({"retryJitterRatio": 0.8})
    with pytest.raises(ProviderConfigError, match="retryDelaySec must be finite"):
        OpenAIRetryPolicy.from_config({"retryDelaySec": float("nan")})


def test_retry_state_keeps_general_and_overload_attempts_independent():
    policy = OpenAIRetryPolicy.from_config(
        {"maxRetries": 1, "overloadMaxRetries": 2}
    )
    state = OpenAIRetryState(policy)

    general = state.next_retry(provider_code="service_unavailable")
    overload_one = state.next_retry(provider_code="server_is_overloaded")
    overload_two = state.next_retry(provider_code="slow_down")

    assert (general.category, general.attempt, general.max_retries) == (
        "general",
        1,
        1,
    )
    assert (overload_one.category, overload_one.attempt) == ("overload", 1)
    assert (overload_two.category, overload_two.attempt) == ("overload", 2)
    assert state.next_retry(provider_code="service_unavailable") is None
    assert state.next_retry(provider_code="server_is_overloaded") is None


@pytest.mark.parametrize(
    ("provider_code", "expected"),
    [
        ("server_error", True),
        ("internal_server_error", True),
        ("service_unavailable", True),
        ("temporarily_unavailable", True),
        ("server_is_overloaded", True),
        ("slow_down", True),
        ("invalid_request_error", False),
        ("server_error in prose", False),
        ("", False),
    ],
)
def test_retryable_provider_code_requires_an_exact_structured_code(
    provider_code,
    expected,
):
    assert is_retryable_provider_code(provider_code) is expected


def test_stream_retries_server_overloaded_with_dedicated_budget(monkeypatch):
    agent = _agent(
        {
            "timeoutMs": 1000,
            "maxRetries": 0,
            "overloadMaxRetries": 4,
            "retryDelaySec": 1,
            "retryMaxDelaySec": 10,
            "retryJitterRatio": 0,
        }
    )
    calls = {"count": 0}
    delays = []
    failed_event = {
        "type": "response.failed",
        "response": {
            "id": "resp-busy",
            "error": {
                "code": "server_is_overloaded",
                "message": "The server is busy.",
            },
        },
    }

    def fake_sse_lines(**_kwargs):
        calls["count"] += 1
        event = failed_event if calls["count"] <= 4 else _completed_event()
        yield json.dumps(event)

    monkeypatch.setattr(agent, "_curl_post_sse_data_lines", fake_sse_lines)
    monkeypatch.setattr(
        "src.providers.openai_retry_transport.sleep_with_cancel",
        lambda delay, _source: delays.append(delay),
    )

    result = agent._stream_responses_with_retry(
        endpoint="responses",
        url="https://api.openai.test/v1/responses",
        headers={},
        payload_json="{}",
        stream_handler=None,
    )

    assert calls["count"] == 5
    assert delays == [1.0, 2.0, 4.0, 8.0]
    assert result["output"][0]["content"][0]["text"] == "ok"
    retry_notices = [
        event for event in agent.events if event.get("stage") == "openai_responses_retry"
    ]
    assert len(retry_notices) == 4
    assert "Attempt 4/4" in retry_notices[-1]["message"]


def test_stream_ordinary_503_does_not_consume_overload_budget(monkeypatch):
    agent = _agent(
        {
            "timeoutMs": 1000,
            "maxRetries": 1,
            "overloadMaxRetries": 8,
            "retryDelaySec": 0,
            "retryJitterRatio": 0,
        }
    )
    calls = {"count": 0}
    failed_event = {
        "type": "response.failed",
        "response": {
            "error": {
                "status_code": 503,
                "code": "service_unavailable",
                "message": "busy",
            }
        },
    }

    def fake_sse_lines(**_kwargs):
        calls["count"] += 1
        yield json.dumps(failed_event)

    monkeypatch.setattr(agent, "_curl_post_sse_data_lines", fake_sse_lines)
    monkeypatch.setattr(
        "src.providers.openai_retry_transport.sleep_with_cancel",
        lambda _delay, _source: None,
    )

    with pytest.raises(RuntimeError, match="service_unavailable"):
        agent._stream_responses_with_retry(
            endpoint="responses",
            url="https://api.openai.test/v1/responses",
            headers={},
            payload_json="{}",
            stream_handler=None,
        )

    assert calls["count"] == 2


def test_websocket_status_zero_overload_uses_dedicated_budget(monkeypatch):
    agent = _agent(
        {
            "timeoutMs": 1000,
            "maxRetries": 0,
            "overloadMaxRetries": 2,
            "retryDelaySec": 0,
            "retryJitterRatio": 0,
        }
    )
    calls = {"count": 0}
    delays = []

    def stream_once(**_kwargs):
        calls["count"] += 1
        if calls["count"] <= 2:
            raise OpenAIHttpError(
                0,
                "Our servers are currently overloaded.",
                provider_code="server_is_overloaded",
            )
        return _completed_event()["response"]

    monkeypatch.setattr(agent, "_stream_responses_once", stream_once)
    monkeypatch.setattr(
        "src.providers.openai_retry_transport.sleep_with_cancel",
        lambda delay, _source: delays.append(delay),
    )

    result = agent._stream_responses_with_retry(
        endpoint="responses",
        url="https://api.openai.test/v1/responses",
        headers={},
        payload_json="{}",
        stream_handler=None,
    )

    assert calls["count"] == 3
    assert delays == [0.0, 0.0]
    notices = [
        event for event in agent.events if event.get("stage") == "openai_responses_retry"
    ]
    assert len(notices) == 2
    assert "Attempt 2/2" in notices[-1]["message"]
    assert result["output"][0]["content"][0]["text"] == "ok"


def test_websocket_status_zero_server_error_uses_general_budget(monkeypatch):
    agent = _agent(
        {
            "timeoutMs": 1000,
            "maxRetries": 1,
            "overloadMaxRetries": 0,
            "retryDelaySec": 0,
            "retryJitterRatio": 0,
        }
    )
    calls = {"count": 0}

    def stream_once(**_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise OpenAIHttpError(
                0,
                "An error occurred while processing your request.",
                provider_code="server_error",
            )
        return _completed_event()["response"]

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

    assert calls["count"] == 2
    assert result["output"][0]["content"][0]["text"] == "ok"


def test_status_zero_error_prose_does_not_enable_retry(monkeypatch):
    agent = _agent(
        {
            "timeoutMs": 1000,
            "maxRetries": 3,
            "retryDelaySec": 0,
            "retryJitterRatio": 0,
        }
    )
    calls = {"count": 0}

    def stream_once(**_kwargs):
        calls["count"] += 1
        raise OpenAIHttpError(
            0,
            "server_error appears only in unstructured prose",
        )

    monkeypatch.setattr(agent, "_stream_responses_once", stream_once)

    with pytest.raises(RuntimeError, match="server_error appears only"):
        agent._stream_responses_with_retry(
            endpoint="responses",
            url="https://api.openai.test/v1/responses",
            headers={},
            payload_json="{}",
            stream_handler=None,
        )

    assert calls["count"] == 1


def test_http_error_extracts_provider_code_only_from_json_error_contract():
    structured = OpenAIHttpError(
        0,
        json.dumps(
            {
                "error": {
                    "type": "server_error",
                    "message": "temporary failure",
                }
            }
        ),
    )
    unstructured = OpenAIHttpError(0, "server_error: temporary failure")

    assert structured.provider_code == "server_error"
    assert unstructured.provider_code == ""
