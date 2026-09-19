from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.cli_provider_runtime.contracts import CanonicalResult
from src.public_gateway.routes import register_public_gateway_routes
from src.public_gateway.service import PublicGatewayService
from src.web_backend.public_gateway_api import PublicGatewayApiDomain
from src.web_backend.route_registry import ApiRouteRegistry


PROTOCOLS = ["responses", "chat_completions", "messages"]
ENDPOINTS = ["/v1/responses", "/v1/chat/completions", "/v1/messages"]


@pytest.fixture
def gateway_models(tmp_path, monkeypatch):
    providers = {
        name: {
            "type": "openai", "model": f"upstream-{name}", "supportmode": ["chat"],
            "authMode": "api_key", "baseUrl": "https://example.invalid/v1", "apiKey": "unused",
        }
        for name in ("alpha", "beta")
    }
    monkeypatch.setattr("src.public_gateway.store.ConfigLoader.get_provider_catalog", lambda _self: providers)
    monkeypatch.setattr("src.public_gateway.store.ConfigLoader.get_provider_config", lambda _self, name: dict(providers[name]))
    monkeypatch.setattr("src.public_gateway.store.list_accounts", lambda _provider: [])
    monkeypatch.setattr("src.public_gateway.store.get_account", lambda _provider, account: {"id": account})
    service = PublicGatewayService(str(tmp_path))
    domain = PublicGatewayApiDomain()
    domain.service = service
    app = FastAPI()
    core = SimpleNamespace(public_gateway_api=domain)
    for method, path, resolver in ApiRouteRegistry.ROUTES:
        if path.startswith("/api/gateway"):
            getattr(app, method)(path)(resolver(core))
    register_public_gateway_routes(app, service)
    client = TestClient(app)
    key = service.create_key({"name": "multi-model test"})["created"]["key"]
    client.headers["Authorization"] = f"Bearer {key}"
    models = [
        {"id": "public/alpha", "providerId": "alpha", "accountId": "", "protocols": PROTOCOLS, "enabled": True},
        {"id": "public/beta", "providerId": "beta", "accountId": "abcdef123456", "protocols": PROTOCOLS, "enabled": True},
        {"id": "public/alpha-second", "providerId": "alpha", "accountId": "", "protocols": PROTOCOLS, "enabled": True},
    ]
    calls = []

    class Adapter:
        def __init__(self, config):
            self.config = config

        def complete(self, request):
            calls.append((self.config, request))
            return CanonicalResult(response_id="resp_test", text=f"ready:{request.model}", input_tokens=3, output_tokens=2)

        def stream(self, request, **_kwargs):
            calls.append((self.config, request))
            yield b'event: response.created\ndata: {"type":"response.created","response":{"id":"resp_test"}}\n\n'
            delta = {"type": "response.output_text.delta", "delta": f"ready:{request.model}"}
            yield f"event: response.output_text.delta\ndata: {json.dumps(delta)}\n\n".encode()
            yield b'event: response.completed\ndata: {"type":"response.completed","response":{"id":"resp_test","usage":{"input_tokens":3,"output_tokens":2}}}\n\n'

    monkeypatch.setattr("src.cli_provider_runtime.gateway_dispatch.create_chat_adapter", Adapter)
    return client, service, models, calls


def request_body(model_id, protocol, stream=False):
    if protocol == "responses":
        return {"model": model_id, "input": "ready?", "stream": stream}
    return {"model": model_id, "messages": [{"role": "user", "content": "ready?"}], "max_tokens": 32, "stream": stream}


@pytest.mark.parametrize("stream", [False, True])
def test_saved_multiple_models_route_each_provider_account_and_protocol(gateway_models, stream):
    client, service, models, calls = gateway_models
    saved = client.put("/api/gateway/models", json={"models": models})
    assert saved.status_code == 200
    assert saved.json()["models"] == models
    assert client.get("/api/gateway").json()["models"] == models
    assert PublicGatewayService(service.workspace_root).settings()["models"] == models
    listed = client.get("/v1/models")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [model["id"] for model in models]

    for model in models:
        for protocol, endpoint in zip(PROTOCOLS, ENDPOINTS):
            response = client.post(endpoint, json=request_body(model["id"], protocol, stream))
            assert response.status_code == 200, response.text
            assert f"ready:{model['id']}" in response.text
            config, request = calls[-1]
            assert config["model"] == request.model == model["id"]
            assert config.get("authAccountId", "") == model["accountId"]
            if stream:
                assert response.headers["content-type"].startswith("text/event-stream")
            else:
                assert response.json()["model"] == model["id"]
    assert len(calls) == 9
    # Both IDs share alpha's connection, but neither uses alpha's default model.
    alpha_calls = [call for call in calls if call[0]["model"] in ("public/alpha", "public/alpha-second")]
    assert {call[1].model for call in alpha_calls} == {"public/alpha", "public/alpha-second"}
    assert all(call[0]["baseUrl"] == "https://example.invalid/v1" for call in alpha_calls)
    assert service.store._resolve_source_config("alpha")["model"] == "upstream-alpha"

    for model in models:
        for protocol in PROTOCOLS:
            result = client.post("/api/gateway/test", json={"model": model["id"], "protocol": protocol})
            assert result.status_code == 200
            assert result.json()["ok"] is True
            assert result.json()["model"] == model["id"]
            assert calls[-1][0].get("authAccountId", "") == model["accountId"]
            assert calls[-1][1].model == model["id"]
    assert len(calls) == 18


def test_edit_remove_disable_and_clear_do_not_mix_models(gateway_models):
    client, _service, models, calls = gateway_models
    assert client.put("/api/gateway/models", json={"models": models}).status_code == 200
    changed = copy.deepcopy(models)
    changed[0]["id"] = "public/renamed"
    changed[0]["protocols"] = ["responses"]
    changed[1]["enabled"] = False
    changed.pop(2)
    assert client.put("/api/gateway/models", json={"models": changed}).json()["models"] == changed
    assert [item["id"] for item in client.get("/v1/models").json()["data"]] == ["public/renamed"]
    for model_id, status in [("public/alpha", 404), ("public/alpha-second", 404), ("public/beta", 503)]:
        assert client.post("/v1/responses", json=request_body(model_id, "responses")).status_code == status
    assert client.post("/v1/chat/completions", json=request_body("public/renamed", "chat_completions")).status_code == 400
    assert calls == []
    assert client.post("/v1/responses", json=request_body("public/renamed", "responses")).status_code == 200
    assert calls[-1][0]["model"] == "public/renamed"
    assert client.put("/api/gateway/models", json={"models": []}).json()["models"] == []
    assert client.get("/v1/models").json()["data"] == []


@pytest.mark.parametrize("invalid", [
    {"id": "public/alpha"},
    {"id": "bad id"},
    {"providerId": "missing-provider"},
    {"accountId": "bad-account"},
    {"protocols": []},
    {"protocols": ["images_generations"]},
    {"enabled": "yes"},
])
def test_invalid_later_row_does_not_partially_save(gateway_models, invalid):
    client, service, models, _calls = gateway_models
    assert client.put("/api/gateway/models", json={"models": models}).status_code == 200
    before = open(service.store.config_path, encoding="utf-8").read()
    changed = copy.deepcopy(models)
    changed[0]["accountId"] = "111111111111"
    changed[-1].update(invalid)
    response = client.put("/api/gateway/models", json={"models": changed})
    assert response.status_code in (400, 404)
    assert open(service.store.config_path, encoding="utf-8").read() == before
    assert client.get("/api/gateway").json()["models"] == models


@pytest.mark.parametrize("payload", [{}, {"models": None}, {"models": {}}, {"models": "public/alpha"}, {"models": [None]}])
def test_models_payload_requires_an_array_of_model_objects(gateway_models, payload):
    client, _service, _models, _calls = gateway_models
    assert client.put("/api/gateway/models", json=payload).status_code == 400


def test_unified_save_persists_options_and_all_models_together(gateway_models):
    client, service, models, _calls = gateway_models
    payload = {"enabled": False, "requireApiKey": False, "models": models}
    response = client.put("/api/gateway", json=payload)
    assert response.status_code == 200
    for name, value in payload.items():
        assert response.json()[name] == value
    reopened = PublicGatewayService(service.workspace_root).settings()
    assert reopened["enabled"] is False
    assert reopened["requireApiKey"] is False
    assert reopened["models"] == models
    assert len(reopened["keys"]) == 1
    # Enable the saved list, then exercise both model IDs sharing one Provider.
    payload["enabled"] = True
    assert client.put("/api/gateway", json=payload).status_code == 200
    for model in models:
        response = client.post("/v1/responses", json=request_body(model["id"], "responses"))
        assert response.status_code == 200
        assert response.json()["model"] == model["id"]


@pytest.mark.parametrize("invalid", [
    {"id": "bad id"}, {"id": "public/alpha"}, {"providerId": "unknown"},
    {"accountId": "bad-account"}, {"protocols": []},
])
def test_unified_save_rejects_all_changes_if_one_model_is_invalid(gateway_models, invalid):
    client, service, models, _calls = gateway_models
    initial = {"enabled": True, "requireApiKey": True, "models": models}
    assert client.put("/api/gateway", json=initial).status_code == 200
    with open(service.store.config_path, encoding="utf-8") as handle:
        before = handle.read()
    changed = copy.deepcopy(models)
    changed[-1].update(invalid)
    response = client.put("/api/gateway", json={"enabled": False, "requireApiKey": False, "models": changed})
    assert response.status_code in (400, 404)
    with open(service.store.config_path, encoding="utf-8") as handle:
        assert handle.read() == before
    snapshot = client.get("/api/gateway").json()
    for name, value in initial.items():
        assert snapshot[name] == value


@pytest.mark.parametrize("payload", [
    {"enabled": False, "requireApiKey": True},
    {"enabled": "false", "requireApiKey": True, "models": []},
    {"enabled": False, "models": []},
    {"enabled": False, "requireApiKey": None, "models": []},
])
def test_unified_save_requires_complete_typed_configuration(gateway_models, payload):
    client, _service, _models, _calls = gateway_models
    assert client.put("/api/gateway", json=payload).status_code == 400
