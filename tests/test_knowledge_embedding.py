import json

import httpx
import pytest
from pydantic import ValidationError

from src.knowledge.contracts import LibraryConfig
from src.knowledge.embedding import Embedder, EmbeddingError
from src.knowledge.embedding import rate_limit_code
from src.provider_api_key_store import add_api_key_alias, api_key_store_path


def config(**overrides):
    return LibraryConfig(**{
        "name": "notes", "folder": "C:/notes", "embedding_model": "test",
        "dimensions": 8, "embedding_url": "http://localhost:11434/v1", **overrides,
    })


def test_rate_limit_diagnostics_only_include_machine_code():
    response = httpx.Response(429, json={"error": {
        "code": "RateLimitExceeded", "message": "secret or document contents",
    }})
    assert rate_limit_code(response) == "RateLimitExceeded"
    assert rate_limit_code(httpx.Response(429, text="not json")) == "unavailable"
    assert rate_limit_code(httpx.Response(429, json={"error": {"code": "secret with spaces"}})) == "unavailable"


@pytest.mark.parametrize("url, expected", [
    ("http://localhost:11434/v1", "http://localhost:11434/v1/embeddings"),
    ("http://localhost:11434/v1/embeddings/", "http://localhost:11434/v1/embeddings"),
    (" https://ark.cn-beijing.volces.com/api/coding/v3/ ",
     "https://ark.cn-beijing.volces.com/api/coding/v3/embeddings"),
    ("https://ark.cn-beijing.volces.com/api/v3", "https://ark.cn-beijing.volces.com/api/v3/embeddings"),
    ("https://ark.cn-beijing.volces.com/api/plan/v3", "https://ark.cn-beijing.volces.com/api/plan/v3/embeddings"),
    ("https://ark.cn-beijing.volces.com/api/plan/v3/embeddings", "https://ark.cn-beijing.volces.com/api/plan/v3/embeddings"),
])
def test_base_url_and_complete_endpoint(url, expected):
    assert config(embedding_url=url).embedding_url == expected


def test_multimodal_protocol_is_explicitly_unsupported():
    with pytest.raises(ValidationError, match="尚未实现多模态请求协议"):
        config(embedding_url="https://example.com/embeddings/multimodal")


@pytest.mark.parametrize("url", ["file:///tmp", "https://user:secret@example.com/v1",
                                     "https://example.com/v1?key=secret", "https://example.com/v1#fragment"])
def test_url_rejects_credentials_and_non_http(url):
    with pytest.raises(ValidationError):
        config(embedding_url=url)


def test_alias_key_resolution_and_request_protocol(tmp_path, monkeypatch):
    add_api_key_alias(api_key_store_path(str(tmp_path)), name="ark", api_key="secret-value")
    requests = []

    def respond(request):
        requests.append(request)
        # Return reversed indices to verify batch ordering.
        return httpx.Response(200, json={"data": [
            {"index": 1, "embedding": [2.0] * 8}, {"index": 0, "embedding": [1.0] * 8},
        ]})

    mock_curl(monkeypatch, respond)
    embedder = Embedder(config(api_key_alias="ark", embedding_url="https://ark.cn-beijing.volces.com/api/plan/v3"), workspace=tmp_path)
    assert embedder.embed(["one", "two"]) == [[1.0] * 8, [2.0] * 8]
    assert requests[0].headers["Authorization"] == "Bearer secret-value"
    assert str(requests[0].url) == "https://ark.cn-beijing.volces.com/api/plan/v3/embeddings"
    assert json.loads(requests[0].content) == {"model": "test", "input": ["one", "two"], "encoding_format": "float"}


def test_missing_alias_is_not_sent_as_a_credential(tmp_path):
    embedder = Embedder(config(api_key_alias="missing"), workspace=tmp_path)
    with pytest.raises(EmbeddingError, match="共享 API Key 存储"):
        embedder.embed(["one"])
    add_api_key_alias(api_key_store_path(str(tmp_path)), name="other", api_key="secret-value")
    with pytest.raises(EmbeddingError, match="API Key Name 不存在"):
        embedder.embed(["one"])
    assert Embedder(config(), workspace=tmp_path).resolve_key() == ""


def test_detect_dimensions_uses_actual_response_and_embed_enforces_bound_dimension(monkeypatch):
    mock_curl(monkeypatch, lambda request: httpx.Response(200, json={
            "data": [{"index": 0, "embedding": [1.0] * 2048}],
        }))
    embedder = Embedder(config(dimensions=1024))
    assert embedder.detect_dimensions() == 2048
    with pytest.raises(EmbeddingError, match="实际返回 2048 维，当前索引为 1024 维"):
        embedder.embed(["test"])


@pytest.mark.parametrize("status, hint", [(401, "API Key"), (403, "权限"), (404, "Base URL"), (429, "配额")])
def test_upstream_error_is_actionable_without_echoing_secrets(monkeypatch, status, hint):
    monkeypatch.setattr("src.knowledge.embedding.time.sleep", lambda seconds: None)
    mock_curl(monkeypatch, lambda request: httpx.Response(status, text="secret-value"))
    with pytest.raises(EmbeddingError, match=hint) as error:
        Embedder(config()).embed(["one"])
    assert "secret-value" not in str(error.value)


@pytest.mark.parametrize("detect", [False, True])
@pytest.mark.parametrize("interval", [5, 12])
def test_429_waits_configured_interval_and_retries_same_request(monkeypatch, detect, interval):
    requests, waits = [], []

    def respond(request):
        requests.append(request.content)
        if len(requests) <= 2:
            return httpx.Response(429)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0] * 8}]})

    mock_curl(monkeypatch, respond)
    monkeypatch.setattr("src.knowledge.embedding.time.sleep", waits.append)
    embedder = Embedder(config(retry_interval_seconds=interval))
    assert (embedder.detect_dimensions() if detect else embedder.embed(["test"])) == (8 if detect else [[1.0] * 8])
    assert waits == [interval, interval]
    assert len(requests) == 3 and len(set(requests)) == 1


@pytest.mark.parametrize("status, attempts, delays", [(429, 4, [5] * 3), (401, 1, []), (500, 1, [])])
def test_retry_is_bounded_and_only_for_429(monkeypatch, status, attempts, delays):
    requests, waits = [], []

    def respond(request):
        requests.append(request)
        return httpx.Response(status)

    mock_curl(monkeypatch, respond)
    monkeypatch.setattr("src.knowledge.embedding.time.sleep", waits.append)
    with pytest.raises(EmbeddingError, match=f"HTTP {status}"):
        Embedder(config()).embed(["test"])
    assert len(requests) == attempts
    assert waits == delays


def test_pause_interrupts_429_wait_before_another_request(monkeypatch):
    from src.knowledge.scanner import Interrupted
    requests, waits = [], []

    class StopDuringWait:
        def is_set(self):
            return False

        def wait(self, seconds):
            waits.append(seconds)
            return True

    def respond(request):
        requests.append(request)
        return httpx.Response(429)

    mock_curl(monkeypatch, respond)
    with pytest.raises(Interrupted):
        Embedder(config(retry_interval_seconds=12), stop=StopDuringWait()).embed(["test"])
    assert len(requests) == 1 and waits == [12]


@pytest.mark.parametrize("interval", [0, -1, 301, 1.5, True])
def test_retry_interval_rejects_invalid_values(interval):
    with pytest.raises(ValidationError):
        config(retry_interval_seconds=interval)


def mock_curl(monkeypatch, handler):
    from src.providers.curl_transport import CurlResponse
    def request(self, **kwargs):
        result = handler(httpx.Request(kwargs["method"], kwargs["url"],
                         headers=kwargs.get("headers"), content=kwargs.get("body")))
        return CurlResponse(result.text, result.status_code, dict(result.headers), result.content)
    monkeypatch.setattr("src.knowledge.embedding.CurlHttpTransport.request", request)
