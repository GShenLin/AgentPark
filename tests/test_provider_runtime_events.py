import pytest
import json
from types import SimpleNamespace

from src.providers.doubao_agent_common import _CurlTransportError
from src.providers.doubao_agent import DouBaoAgent
from src.providers.gemini_agent import GeminiAgent


def _build_doubao_agent():
    agent = DouBaoAgent.__new__(DouBaoAgent)
    agent.config = {
        "timeoutMs": 1000,
    }
    agent.provider_name = "doubao"
    agent.events = []
    agent.tool_event_callback = agent.events.append
    return agent


def _build_gemini_agent():
    agent = GeminiAgent.__new__(GeminiAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://example.test/v1",
        "model": "gemini-test",
        "maxRetries": 1,
        "retryDelaySec": 0.25,
        "timeoutMs": 1000,
    }
    agent.provider_name = "gemini"
    agent.events = []
    agent.tool_event_callback = agent.events.append
    return agent


def test_provider_runtime_notice_builds_runtime_notice_event():
    agent = _build_doubao_agent()

    agent._emit_provider_runtime_notice(message="hello", stage="unit")

    assert len(agent.events) == 1
    assert agent.events[0]["type"] == "runtime_notice"
    assert agent.events[0]["message"] == "hello"
    assert agent.events[0]["source"] == "provider_runtime"
    assert agent.events[0]["stage"] == "unit"
    assert agent.events[0]["provider"] == "doubao"
    assert agent.events[0]["event_time"]
    assert isinstance(agent.events[0]["monotonic_ns"], int)


def test_sse_debug_switch_accepts_only_canonical_sse_debug_key():
    agent = _build_doubao_agent()

    agent.config = {"sse_debug": True, "debugSse": True, "debug_sse": True}
    assert agent._provider_sse_debug_enabled() is False

    agent.config = {"sseDebug": True}
    assert agent._provider_sse_debug_enabled() is True


def test_doubao_stream_parse_reports_malformed_sse_event():
    agent = _build_doubao_agent()

    parsed = agent._parse_sse_json_event("{bad", stage="responses_stream_parse")

    assert parsed is None
    assert agent.events[0]["type"] == "runtime_notice"
    assert agent.events[0]["stage"] == "responses_stream_parse"
    assert "malformed SSE event JSON" in agent.events[0]["message"]


def test_gemini_stream_parse_reports_malformed_sse_event():
    agent = _build_gemini_agent()

    parsed = agent._parse_sse_json_event("{bad", stage="gemini_stream_parse")

    assert parsed is None
    assert agent.events[0]["type"] == "runtime_notice"
    assert agent.events[0]["provider"] == "gemini"
    assert agent.events[0]["stage"] == "gemini_stream_parse"
    assert "malformed SSE event JSON" in agent.events[0]["message"]


def test_doubao_post_retry_uses_runtime_notice_instead_of_stdout(monkeypatch, capsys):
    agent = _build_doubao_agent()
    attempts = {"count": 0}

    def fake_post_once(**_kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise _CurlTransportError("temporary transport failure")
        return {"ok": True}

    monkeypatch.setattr(agent, "_curl_post_json_once", fake_post_once)
    monkeypatch.setattr("src.providers.doubao_http_transport.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("src.providers.doubao_http_transport.random.uniform", lambda _a, _b: 0)

    result = agent._post_json_with_retry(
        endpoint="chat/completions",
        url="https://example.test/v1/chat/completions",
        headers={},
        payload_json="{}",
        max_retries=1,
        retry_delay=0.25,
    )

    assert result == {"ok": True}
    assert attempts["count"] == 2
    assert capsys.readouterr().out == ""
    assert agent.events[0]["type"] == "runtime_notice"
    assert agent.events[0]["stage"] == "post_json_retry"
    assert "temporary transport failure" in agent.events[0]["message"]


def test_doubao_post_retry_accepts_operation_timeout(monkeypatch):
    agent = _build_doubao_agent()
    observed = {}

    def fake_post_once(**kwargs):
        observed.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(agent, "_curl_post_json_once", fake_post_once)

    result = agent._post_json_with_retry(
        endpoint="images/generations",
        url="https://example.test/v1/images/generations",
        headers={},
        payload_json="{}",
        max_retries=0,
        retry_delay=1,
        timeout_ms=180_000,
    )

    assert result == {"ok": True}
    assert observed["timeout_sec"] == 180


def test_doubao_image_generation_start_uses_runtime_notice_instead_of_stdout(tmp_path, capsys):
    agent = _build_doubao_agent()
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "agent.md"))
    agent.config.update(
        {
            "apiKey": "test-key",
            "baseUrl": "https://example.test/v1",
            "model": "seedream-test",
            "maxRetries": 0,
            "retryDelaySec": 0,
            "imageGenerationTimeoutMs": 180_000,
            "imageGenerationMaxRetries": 0,
        }
    )
    captured = {}

    request = {}

    def fake_post(**kwargs):
        request.update(kwargs)
        captured.update(json.loads(kwargs["payload_json"]))
        return {"data": [{"b64_json": "cG5n", "output_format": "png"}]}

    agent._post_json_with_retry = fake_post
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent.Message = lambda *_args, **_kwargs: None

    result = agent.generate_image("draw", response_format="b64_json", output_format="png")

    assert result.endswith(".png")
    assert captured["output_format"] == "png"
    assert request["timeout_ms"] == 180_000
    assert request["max_retries"] == 0
    assert capsys.readouterr().out == ""
    assert agent.events[0]["type"] == "runtime_notice"
    assert agent.events[0]["stage"] == "image_generation_start"
    assert "seedream-test" in agent.events[0]["message"]


def test_gemini_image_generation_retry_uses_runtime_notice(monkeypatch, tmp_path, capsys):
    agent = _build_gemini_agent()
    agent.memory = SimpleNamespace(current_memory_path=str(tmp_path / "agent.md"))
    agent.Message = lambda *_args, **_kwargs: None
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    calls = {"count": 0}

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return (
                b'{"candidates":[{"content":{"parts":[{"inlineData":'
                b'{"mimeType":"image/png","data":"cG5n"}}]}}]}'
            )

    def fake_urlopen(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary gemini failure")
        return _Response()

    monkeypatch.setattr("src.providers.gemini_image_generation.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("src.providers.gemini_image_generation.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("src.providers.gemini_image_generation.random.uniform", lambda _a, _b: 0)

    result = agent.generate_image("draw")

    assert result["status"] == "success"
    assert calls["count"] == 2
    assert capsys.readouterr().out == ""
    assert agent.events[0]["type"] == "runtime_notice"
    assert agent.events[0]["stage"] == "gemini_image_generation_retry"
    assert "temporary gemini failure" in agent.events[0]["message"]
