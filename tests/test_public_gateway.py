from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.cli_provider_runtime.contracts import CanonicalResult
from src.cli_provider_runtime.contracts import CanonicalToolCall
from src.cli_provider_runtime.chat_wire import responses_sse_to_chat
from src.cli_provider_runtime.gateway_dispatch import dispatch_chat_completions
from src.cli_provider_runtime.gateway_dispatch import dispatch_messages
from src.cli_provider_runtime.gateway_dispatch import dispatch_responses
from src.cli_provider_runtime.gateway_dispatch import GatewayDispatchResult
from src.cli_provider_runtime.responses_stream import collect_responses_stream
from src.public_gateway.routes import register_public_gateway_routes
from src.public_gateway.service import PublicGatewayService
from src.public_gateway.store import PublicGatewayStore


def test_gateway_key_lifecycle_uses_one_time_plaintext(tmp_path):
    store = PublicGatewayStore(str(tmp_path))

    created = store.create_key({"name": "test client"})

    assert created["key"].startswith("apg_")
    assert store.authenticate(created["key"]) is True
    listed = store.list_keys()
    assert listed == [
        {
            "id": created["id"],
            "name": "test client",
            "prefix": created["prefix"],
            "createdAt": created["createdAt"],
        }
    ]
    assert "key" not in listed[0]

    store.delete_key(created["id"])
    assert store.authenticate(created["key"]) is False
    assert store.list_keys() == []


def test_public_routes_require_endpoint_key_and_list_configured_models(tmp_path, monkeypatch):
    provider_config = {
        "type": "openai",
        "model": "upstream-model",
        "supportmode": ["chat"],
        "authMode": "api_key",
        "baseUrl": "https://example.invalid/v1",
        "apiKey": "unused",
    }
    monkeypatch.setattr(
        "src.public_gateway.store.ConfigLoader.get_provider_catalog",
        lambda _self: {"test-provider": provider_config},
    )
    monkeypatch.setattr(
        "src.public_gateway.store.ConfigLoader.get_provider_config",
        lambda _self, _provider_id: dict(provider_config),
    )
    service = PublicGatewayService(str(tmp_path))
    provider = service.store.list_providers()[0]
    service.store.upsert_model(
        {
            "id": "public/test-model",
            "providerId": provider["id"],
            "accountId": "",
            "protocols": ["responses", "chat_completions", "messages"],
            "enabled": True,
        }
    )
    created = service.store.create_key({"name": "route test"})
    app = FastAPI()
    register_public_gateway_routes(app, service)
    client = TestClient(app)

    unauthorized = client.get("/v1/models")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["type"] == "agentpark_gateway_error"

    response = client.get(
        "/v1/models",
        headers={"Authorization": f"Bearer {created['key']}"},
    )
    assert response.status_code == 200
    assert response.json()["data"] == [
        {
            "id": "public/test-model",
            "object": "model",
            "created": 0,
            "owned_by": "agentpark",
            "metadata": {
                "providerId": provider["id"],
                "protocols": ["responses", "chat_completions", "messages"],
            },
        }
    ]


class _FakeAdapter:
    def __init__(self) -> None:
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return CanonicalResult(
            response_id="resp_test",
            text="ready",
            tool_calls=[
                CanonicalToolCall(
                    call_id="call_1",
                    name="lookup",
                    arguments='{"value":"x"}',
                )
            ],
            input_tokens=3,
            output_tokens=2,
        )

    def stream(self, request, *, response_id=""):
        raise AssertionError("stream was not requested")


def test_shared_dispatch_converts_all_public_protocols(monkeypatch):
    adapter = _FakeAdapter()
    monkeypatch.setattr(
        "src.cli_provider_runtime.gateway_dispatch.create_chat_adapter",
        lambda _config: adapter,
    )
    monkeypatch.setattr(
        "src.cli_provider_runtime.gateway_dispatch.provider_protocol",
        lambda _config: "openai_chat",
    )
    config = {"model": "upstream-model", "type": "openai"}
    tool = {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "Lookup",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        },
    }

    chat = dispatch_chat_completions(
        config,
        {
            "model": "public-model",
            "messages": [{"role": "user", "content": "go"}],
            "tools": [tool],
        },
    )
    assert chat.json_body["object"] == "chat.completion"
    assert chat.json_body["choices"][0]["finish_reason"] == "tool_calls"

    responses = dispatch_responses(
        config,
        {
            "model": "public-model",
            "input": "go",
            "tools": [
                {
                    "type": "function",
                    "name": "lookup",
                    "description": "Lookup",
                    "parameters": tool["function"]["parameters"],
                }
            ],
        },
    )
    assert responses.json_body["object"] == "response"
    assert responses.json_body["output"][1]["type"] == "function_call"

    messages = dispatch_messages(
        config,
        {
            "model": "public-model",
            "messages": [{"role": "user", "content": "go"}],
            "tools": [
                {
                    "name": "lookup",
                    "description": "Lookup",
                    "input_schema": tool["function"]["parameters"],
                }
            ],
            "max_tokens": 64,
        },
    )
    assert messages.json_body["type"] == "message"
    assert messages.json_body["stop_reason"] == "tool_use"
    assert [request.model for request in adapter.requests] == [
        "upstream-model",
        "upstream-model",
        "upstream-model",
    ]


def test_chat_stream_conversion_keeps_one_completion_id_and_done_marker():
    chunks = [
        b'event: response.created\ndata: {"type":"response.created","response":{"id":"resp_1"}}\n\n',
        b'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"OK"}\n\n',
        b'event: response.completed\ndata: {"type":"response.completed","response":{"usage":{"input_tokens":2,"output_tokens":1}}}\n\n',
    ]

    frames = list(responses_sse_to_chat(chunks, model="public-model"))
    payloads = [
        frame.split(b"data: ", 1)[1].strip()
        for frame in frames
        if frame.startswith(b"data: {")
    ]
    decoded = [json.loads(payload) for payload in payloads]

    assert len({item["id"] for item in decoded}) == 1
    assert decoded[1]["choices"][0]["delta"]["content"] == "OK"
    assert decoded[-1]["choices"][0]["finish_reason"] == "stop"
    assert frames[-1] == b"data: [DONE]\n\n"


def test_responses_stream_collector_builds_non_stream_response():
    response = collect_responses_stream(
        [
            b'event: response.created\ndata: {"type":"response.created","response":{"id":"resp_1","model":"m"}}\n\n',
            b'event: response.output_text.delta\ndata: {"type":"response.output_text.delta","delta":"READY"}\n\n',
            b'event: response.completed\ndata: {"type":"response.completed","response":{"id":"resp_1","usage":{"input_tokens":1,"output_tokens":1}}}\n\n',
        ]
    )

    assert response["id"] == "resp_1"
    assert response["object"] == "response"
    assert response["status"] == "completed"
    assert response["output_text"] == "READY"


def test_public_stream_reports_midstream_failure_as_protocol_event():
    class Service:
        @staticmethod
        def authorize(_authorization, _x_api_key):
            return True

        @staticmethod
        def dispatch(_protocol, _payload):
            def chunks():
                yield b'event: response.created\ndata: {"type":"response.created"}\n\n'
                raise RuntimeError("upstream disconnected")

            return GatewayDispatchResult(
                status=200,
                content_type="text/event-stream",
                stream=chunks(),
            )

        @staticmethod
        def models():
            return {"object": "list", "data": []}

    app = FastAPI()
    register_public_gateway_routes(app, Service())

    response = TestClient(app).post("/v1/responses", json={"model": "test"})

    assert response.status_code == 200
    assert "response.created" in response.text
    assert "response.failed" in response.text
    assert "upstream disconnected" in response.text
