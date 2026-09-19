import io
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.cli_provider_runtime.http_transport import UpstreamHttpError, UpstreamResponse
from src.provider_auth.credentials import ProviderRequestCredentials
from src.public_gateway.routes import register_public_gateway_routes
from src.public_gateway.service import PublicGatewayService
from src.public_gateway.usage_stats import extract_gateway_usage


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    config = {
        "type": "openai", "model": "gpt-image-2.5", "supportmode": ["image_generation"],
        "authMode": "codex", "timeoutMs": 180000,
    }
    monkeypatch.setattr("src.public_gateway.store.ConfigLoader.get_provider_config", lambda *args: dict(config))
    monkeypatch.setattr("src.public_gateway.store.ConfigLoader.get_provider_catalog", lambda *args: {"image": config})
    service = PublicGatewayService(str(tmp_path))
    service.store.replace_models({"models": [{"id": "public-image", "providerId": "image", "protocols": ["images_generations", "images_edits"]}]})
    key = service.create_key({"name": "test"})["created"]["key"]
    calls = []
    refreshes = []

    def credentials(config, *, force_refresh):
        refreshes.append(force_refresh)
        return ProviderRequestCredentials("https://chatgpt.com/backend-api/codex", {"Authorization": "Bearer upstream-secret"})

    monkeypatch.setattr("src.cli_provider_runtime.images_dispatch.resolve_provider_request_credentials", credentials)
    response = {"created": 1, "data": [{"b64_json": "aW1hZ2U="}], "usage": {"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}}

    def upstream(**kwargs):
        calls.append(kwargs)
        if kwargs["stream"]:
            body = b'event: image_generation.completed\ndata: {"type":"image_generation.completed","b64_json":"aW1hZ2U="}\n\n'
            return UpstreamResponse(200, {"content-type": "text/event-stream"}, io.BytesIO(body))
        return UpstreamResponse(200, {"content-type": "application/json"}, io.BytesIO(json.dumps(response).encode()))

    monkeypatch.setattr("src.cli_provider_runtime.images_dispatch.open_json_request", upstream)
    app = FastAPI()
    register_public_gateway_routes(app, service)
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {key}"
        yield client, service, calls, response, config, refreshes


@pytest.mark.parametrize("endpoint,extra", [
    ("generations", {"n": 1, "size": "auto", "background": "transparent"}),
    ("edits", {"images": [{"image_url": "data:image/png;base64,aW1hZ2U="}], "quality": "auto"}),
])
def test_forwards_image_request_and_response_without_chat_conversion(gateway, endpoint, extra):
    client, service, calls, body, _, _ = gateway
    payload = {"model": "public-image", "prompt": "private prompt", **extra}
    result = client.post(f"/v1/images/{endpoint}", json=payload)
    assert result.status_code == 200
    assert result.json() == body
    request, = calls
    assert request["url"] == f"https://chatgpt.com/backend-api/codex/images/{endpoint}"
    assert request["payload"] == payload
    assert request["headers"]["Authorization"] == "Bearer upstream-secret"
    assert request["headers"]["Accept"] == "application/json"
    assert request["policy"].timeout_seconds == 180
    assert request["policy"].max_retries == 0
    log = open(service.workspace_root + "/.runtime/public-gateway-access.log", encoding="utf-8").read()
    assert result.headers["x-request-id"] in log
    assert '"upstreamModel":"public-image"' in log
    assert "private prompt" not in log and "upstream-secret" not in log and "aW1hZ2U=" not in log


def test_images_are_advertised_and_cannot_be_used_for_chat(gateway):
    client, service, calls, _, _, _ = gateway
    provider, = service.store.list_providers()
    assert provider["protocol"] == "images"
    assert provider["protocols"] == ["images_generations", "images_edits"]
    assert client.get("/v1/models").json()["data"][0]["id"] == "public-image"
    assert client.post("/v1/responses", json={"model": "public-image", "input": "hi"}).status_code == 400
    with pytest.raises(ValueError, match="does not support"):
        service.store.replace_models({"models": [{"id": "bad", "providerId": "image", "protocols": ["responses"]}]})
    assert not calls


def test_authentication_and_unknown_model_do_not_reach_upstream(gateway):
    client, _, calls, _, _, _ = gateway
    result = client.post("/v1/images/generations", headers={"Authorization": "Bearer wrong"}, json={"model": "public-image", "prompt": "hi"})
    assert result.status_code == 401
    assert client.post("/v1/images/generations", json={"model": "absent", "prompt": "hi"}).status_code == 404
    assert not calls


@pytest.mark.parametrize("extra", [{"prompt": ""}, {"stream": "false"}])
def test_invalid_generation_is_rejected(gateway, extra):
    client, _, calls, _, _, _ = gateway
    result = client.post("/v1/images/generations", json={"model": "public-image", "prompt": "draw", **extra})
    assert result.status_code == 400
    assert not calls


@pytest.mark.parametrize("images", [[], ["file:///private.png"], [{"image_url": "C:/private.png"}], [{"image_url": "file:///private.png"}]])
def test_edit_cannot_read_gateway_local_files(gateway, images):
    client, _, calls, _, _, _ = gateway
    result = client.post("/v1/images/edits", json={"model": "public-image", "prompt": "edit", "images": images})
    assert result.status_code == 400
    assert not calls


def test_image_stream_keeps_native_events(gateway):
    client, _, calls, _, _, _ = gateway
    result = client.post("/v1/images/generations", json={"model": "public-image", "prompt": "draw", "stream": True})
    assert result.status_code == 200
    assert calls[0]["headers"]["Accept"] == "text/event-stream"
    assert result.text == 'event: image_generation.completed\ndata: {"type":"image_generation.completed","b64_json":"aW1hZ2U="}\n\n'


def test_upstream_error_is_not_masked(gateway, monkeypatch):
    client, _, _, _, _, _ = gateway
    def fail(**kwargs):
        raise UpstreamHttpError(403, b'{"error":{"message":"model access denied"}}')
    monkeypatch.setattr("src.cli_provider_runtime.images_dispatch.open_json_request", fail)
    result = client.post("/v1/images/generations", json={"model": "public-image", "prompt": "draw"})
    assert result.status_code == 403
    assert result.json()["error"]["message"] == "model access denied"


def test_oauth_refreshes_once_on_401(gateway, monkeypatch):
    client, _, _, _, _, refreshes = gateway
    def fail(**kwargs):
        raise UpstreamHttpError(401, b'{"error":"expired"}')
    monkeypatch.setattr("src.cli_provider_runtime.images_dispatch.open_json_request", fail)
    result = client.post("/v1/images/generations", json={"model": "public-image", "prompt": "draw"})
    assert result.status_code == 401
    assert refreshes == [False, True]


def test_unmatched_and_invalid_requests_are_logged(gateway):
    client, service, calls, _, _, _ = gateway
    unknown = client.post("/v1/images/unknown", json={"secret": "do not log"})
    malformed = client.post("/v1/images/generations", content="{", headers={"Content-Type": "application/json"})
    assert unknown.status_code == 404
    assert malformed.status_code == 422
    log = open(service.workspace_root + "/.runtime/public-gateway-access.log", encoding="utf-8").read()
    assert unknown.headers["x-request-id"] in log
    assert malformed.headers["x-request-id"] in log
    assert "do not log" not in log
    assert not calls


def test_image_usage_is_counted(gateway):
    _, _, _, body, _, _ = gateway
    usage = extract_gateway_usage("images_generations", body)
    assert usage["total_tokens"] == 5


def test_management_test_uses_images_endpoint(gateway):
    _, service, calls, body, _, _ = gateway
    result = service.test({"model": "public-image", "protocol": "images_generations", "prompt": "draw"})
    assert result["response"] == body
    assert calls[0]["url"].endswith("/images/generations")


@pytest.mark.parametrize("stream", [False, True])
def test_multiple_image_ids_share_provider_but_keep_requested_upstream_model(gateway, stream):
    client, service, calls, _, config, _ = gateway
    model_ids = ["image-model-a", "image-model-b", "image-model-c"]
    service.replace_models({"models": [
        {"id": model_id, "providerId": "image", "protocols": ["images_generations", "images_edits"]}
        for model_id in model_ids
    ]})
    for model_id in model_ids:
        for endpoint in ("generations", "edits"):
            payload = {"model": model_id, "prompt": "draw", "stream": stream}
            if endpoint == "edits":
                payload["images"] = [{"image_url": "https://example.invalid/reference.png"}]
            result = client.post(f"/v1/images/{endpoint}", json=payload)
            assert result.status_code == 200
            assert calls[-1]["payload"]["model"] == model_id
            assert calls[-1]["url"] == f"https://chatgpt.com/backend-api/codex/images/{endpoint}"
    assert len(calls) == 6
    assert config["model"] == "gpt-image-2.5"
