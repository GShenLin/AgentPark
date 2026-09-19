import pytest

from src.providers.deepseek_errors import DeepSeekRuntimeError, deepseek_transport_error
from src.providers.openai_transport_errors import OpenAIHttpError, OpenAITransportError


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (401, '{"error":{"message":"invalid key"}}', "AUTH"),
        (403, '{"error":{"message":"forbidden"}}', "AUTH"),
        (402, '{"error":{"message":"Insufficient Balance"}}', "QUOTA"),
        (429, '{"error":{"message":"busy"}}', "RATE_LIMIT"),
        (400, '{"error":{"message":"maximum context length exceeded"}}', "CONTEXT_WINDOW_EXCEEDED"),
        (400, '{"error":{"code":"context_length_exceeded"}}', "CONTEXT_WINDOW_EXCEEDED"),
        (400, '{"error":{"message":"invalid field"}}', "INVALID_REQUEST"),
        (500, '{"error":{"message":"server failed"}}', "SERVER"),
        (418, '{"error":{"message":"teapot"}}', "HTTP_418"),
    ],
)
def test_deepseek_http_errors_have_stable_codes(status, body, code):
    error = deepseek_transport_error("responses", OpenAIHttpError(status, body))

    assert isinstance(error, DeepSeekRuntimeError)
    assert error.code == code
    assert error.status_code == status


def test_deepseek_transport_error_has_stable_code():
    error = deepseek_transport_error("responses", OpenAITransportError("connection refused"))

    assert error.code == "TRANSPORT"
    assert error.status_code == 0


def test_deepseek_agent_applies_stable_errors_to_responses_transport(monkeypatch):
    from tests.test_deepseek_chat_runtime import _build_deepseek_agent

    agent = _build_deepseek_agent()
    monkeypatch.setattr(
        agent,
        "_curl_post_json_once",
        lambda **_kwargs: (_ for _ in ()).throw(
            OpenAIHttpError(400, '{"error":{"code":"context_length_exceeded"}}')
        ),
    )

    with pytest.raises(DeepSeekRuntimeError) as raised:
        agent._post_json_with_retry(
            endpoint="responses",
            url="https://api.deepseek.test/responses",
            headers={},
            payload_json="{}",
        )

    assert raised.value.code == "CONTEXT_WINDOW_EXCEEDED"


def test_deepseek_malformed_sse_has_stable_code():
    from src.providers.deepseek_chat_runtime import DeepSeekChatRuntime
    from tests.test_deepseek_chat_runtime import _build_deepseek_agent

    runtime = DeepSeekChatRuntime(_build_deepseek_agent())
    with pytest.raises(DeepSeekRuntimeError) as raised:
        runtime._parse_sse_json_event("{not-json", stage="chat/completions")

    assert raised.value.code == "MALFORMED_RESPONSE"


def test_deepseek_stream_requires_done_sentinel():
    from src.providers.deepseek_chat_runtime import DeepSeekChatRuntime
    from tests.test_deepseek_chat_runtime import _build_deepseek_agent

    runtime = DeepSeekChatRuntime(_build_deepseek_agent())
    with pytest.raises(DeepSeekRuntimeError) as raised:
        runtime._validate_chat_stream_completion(saw_done=False)

    assert raised.value.code == "STREAM_CLOSED"


def test_deepseek_empty_response_has_stable_code():
    from src.providers.deepseek_chat_runtime import DeepSeekChatRuntime
    from tests.test_deepseek_chat_runtime import _build_deepseek_agent

    runtime = DeepSeekChatRuntime(_build_deepseek_agent())
    with pytest.raises(DeepSeekRuntimeError) as raised:
        runtime._handle_chat_completions_result(
            {"choices": [{"message": {"role": "assistant", "content": ""}}]},
            run_tools=False,
            reasoning_effort="high",
            thinking_mode="enabled",
            web_search_mode="disabled",
            stream=False,
            stream_handler=None,
        )

    assert raised.value.code == "EMPTY_RESPONSE"
