from __future__ import annotations

import json

import pytest

from src.codex_runtime import http_transport
from src.codex_runtime.http_transport import UpstreamRequestPolicy
from src.codex_runtime.http_transport import UpstreamTransportError
from src.codex_runtime.http_transport import iter_sse_data
from src.codex_runtime.http_transport import open_json_request
from src.codex_runtime.http_transport import read_json_response
from src.providers.curl_transport import CurlResponse
from src.providers.curl_transport import CurlTransportError


POLICY = UpstreamRequestPolicy(timeout_seconds=5, max_retries=2, retry_delay_seconds=0)


def _open(*, stream: bool):
    return open_json_request(
        url="https://provider.example/v1/responses",
        headers={"Authorization": "Bearer secret"},
        payload={"model": "model", "input": "hello", "stream": stream},
        policy=POLICY,
        stream=stream,
    )


def test_non_stream_request_retries_curl_transport_failure(monkeypatch):
    class Transport:
        attempts = 0

        def post_json_response(self, **_kwargs):
            self.attempts += 1
            if self.attempts < 3:
                raise CurlTransportError("TLS EOF")
            return CurlResponse(body='{"ok":true}', status_code=200)

    transport = Transport()
    monkeypatch.setattr(http_transport, "_CURL", transport)

    assert read_json_response(_open(stream=False)) == {"ok": True}
    assert transport.attempts == 3


def test_stream_request_retries_before_first_sse_event(monkeypatch):
    class Transport:
        attempts = 0

        def stream_sse_data(self, **_kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise CurlTransportError("TLS EOF")
            yield json.dumps({"type": "response.created", "response": {"id": "resp"}})
            yield CurlResponse(body="", status_code=200)

    transport = Transport()
    monkeypatch.setattr(http_transport, "_CURL", transport)

    events = [json.loads(data) for data in iter_sse_data(_open(stream=True))]

    assert events[0]["type"] == "response.created"
    assert transport.attempts == 2


def test_stream_request_does_not_retry_after_first_sse_event(monkeypatch):
    class Transport:
        attempts = 0

        def stream_sse_data(self, **_kwargs):
            self.attempts += 1
            yield json.dumps({"type": "response.created", "response": {"id": "resp"}})
            raise CurlTransportError("TLS EOF after response started")

    transport = Transport()
    monkeypatch.setattr(http_transport, "_CURL", transport)
    response = _open(stream=True)

    with pytest.raises(UpstreamTransportError, match="after 1 attempt"):
        list(iter_sse_data(response))

    assert transport.attempts == 1
