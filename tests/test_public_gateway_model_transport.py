"""Exercise real gateway adapters, substituting only the upstream HTTP boundary."""
import io
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.cli_provider_runtime.http_transport import UpstreamResponse
from src.provider_auth.credentials import ProviderRequestCredentials
from src.public_gateway.routes import register_public_gateway_routes
from src.public_gateway.service import PublicGatewayService


@pytest.mark.parametrize("native_responses", [False, True])
@pytest.mark.parametrize("stream", [False, True])
def test_same_provider_sends_each_model_id_in_upstream_http_body(tmp_path, monkeypatch, native_responses, stream):
    config = {
        "type": "openai", "model": "default-must-not-be-used", "responsesApi": native_responses,
        "supportmode": ["chat"], "authMode": "api_key", "baseUrl": "https://example.invalid/v1",
    }
    monkeypatch.setattr("src.public_gateway.store.ConfigLoader.get_provider_config", lambda *_: dict(config))
    monkeypatch.setattr("src.public_gateway.store.ConfigLoader.get_provider_catalog", lambda *_: {"shared": config})
    monkeypatch.setattr("src.public_gateway.store.list_accounts", lambda *_: [])
    calls = []

    def credentials(*_args, **_kwargs):
        return ProviderRequestCredentials("https://example.invalid/v1", {"Authorization": "Bearer fixture-key"})

    def upstream(**kwargs):
        calls.append(kwargs)
        model_id = kwargs["payload"]["model"]
        if native_responses:
            response = {"id": "resp_test", "object": "response", "model": model_id,
                        "output_text": "ready", "output": [], "status": "completed"}
            frames = [
                {"type": "response.created", "response": {"id": "resp_test", "model": model_id}},
                {"type": "response.output_text.delta", "delta": "ready"},
                {"type": "response.completed", "response": response},
            ]
            sse = "".join(f"event: {frame['type']}\ndata: {json.dumps(frame)}\n\n" for frame in frames)
        else:
            response = {"id": "chat_test", "model": model_id, "choices": [
                {"index": 0, "message": {"role": "assistant", "content": "ready"}, "finish_reason": "stop"},
            ]}
            frames = [
                {"id": "chat_test", "choices": [{"index": 0, "delta": {"content": "ready"}}]},
                {"id": "chat_test", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            ]
            sse = "".join(f"data: {json.dumps(frame)}\n\n" for frame in frames) + "data: [DONE]\n\n"
        content_type = "text/event-stream" if kwargs["stream"] else "application/json"
        body = sse if kwargs["stream"] else json.dumps(response)
        return UpstreamResponse(200, {"content-type": content_type}, io.BytesIO(body.encode()))

    module = "gateway_dispatch" if native_responses else "openai_chat_adapter"
    monkeypatch.setattr(f"src.cli_provider_runtime.{module}.resolve_provider_request_credentials", credentials)
    monkeypatch.setattr(f"src.cli_provider_runtime.{module}.open_json_request", upstream)
    service = PublicGatewayService(str(tmp_path))
    model_ids = ["model-a", "model-b", "model-c"]
    service.replace_models({"models": [
        {"id": model_id, "providerId": "shared", "protocols": ["responses", "chat_completions", "messages"]}
        for model_id in model_ids
    ]})
    key = service.create_key({"name": "transport-test"})["created"]["key"]
    app = FastAPI()
    register_public_gateway_routes(app, service)
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {key}"
    endpoints = ["responses"] if native_responses else ["responses", "chat/completions", "messages"]
    for model_id in model_ids:
        for endpoint in endpoints:
            payload = {"model": model_id, "stream": stream}
            if endpoint == "responses":
                payload["input"] = "ready?"
            else:
                payload.update(messages=[{"role": "user", "content": "ready?"}], max_tokens=32)
            result = client.post(f"/v1/{endpoint}", json=payload)
            assert result.status_code == 200, result.text
            assert "ready" in result.text
            assert calls[-1]["payload"]["model"] == model_id
            expected_path = "responses" if native_responses else "chat/completions"
            assert calls[-1]["url"] == f"https://example.invalid/v1/{expected_path}"
            assert calls[-1]["headers"]["Authorization"] == "Bearer fixture-key"
    assert len(calls) == len(model_ids) * len(endpoints)
    assert config["model"] == "default-must-not-be-used"
