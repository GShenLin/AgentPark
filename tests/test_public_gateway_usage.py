from __future__ import annotations

from datetime import datetime
from datetime import timedelta
from datetime import timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.cli_provider_runtime.gateway_dispatch import GatewayDispatchResult
from src.public_gateway.routes import register_public_gateway_routes
from src.public_gateway.usage_stats import GatewayUsageAccumulator
from src.public_gateway.usage_stats import PublicGatewayUsageStore
from src.public_gateway.usage_stats import extract_gateway_usage


def test_extract_gateway_usage_normalizes_all_non_stream_protocols():
    assert extract_gateway_usage(
        "responses",
        {
            "object": "response",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 4,
                "total_tokens": 14,
                "input_tokens_details": {"cached_tokens": 6},
            },
        },
    ) == {
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
        "cached_input_tokens": 6,
    }
    assert extract_gateway_usage(
        "chat_completions",
        {"usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}},
    ) == {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}
    assert extract_gateway_usage(
        "messages",
        {"type": "message", "usage": {"input_tokens": 8, "output_tokens": 2}},
    ) == {"input_tokens": 8, "output_tokens": 2, "total_tokens": 10}


def test_stream_accumulator_handles_split_frames_and_anthropic_usage_events():
    accumulator = GatewayUsageAccumulator("messages")
    accumulator.consume_stream_chunk(
        b'event: message_start\ndata: {"type":"message_start","message":{"usage":{"input_tokens":12,'
    )
    accumulator.consume_stream_chunk(
        b'"output_tokens":0}}}\n\nevent: message_delta\ndata: {"type":"message_delta",'
        b'"usage":{"output_tokens":5}}\n\n'
    )

    assert accumulator.usage() == {
        "input_tokens": 12,
        "output_tokens": 5,
        "total_tokens": 17,
    }


def test_usage_store_aggregates_by_date_ip_and_model_and_reports_missing_usage(tmp_path):
    store = PublicGatewayUsageStore(str(tmp_path))
    moment = datetime(2026, 8, 26, 12, 0, tzinfo=timezone(timedelta(hours=8)))
    selected_date = moment.astimezone().date().isoformat()
    records = [
        ("r1", "10.0.0.2", "public/a", {"input_tokens": 10, "output_tokens": 3}),
        ("r2", "10.0.0.2", "public/b", {"input_tokens": 4, "output_tokens": 2}),
        ("r3", "10.0.0.3", "public/a", {}),
    ]
    for request_id, client_ip, model_id, usage in records:
        store.record_completed(
            request_id=request_id,
            client_ip=client_ip,
            model_id=model_id,
            protocol="responses",
            usage=usage,
            recorded_at=moment,
        )

    result = store.aggregate(selected_date)

    assert result["totals"] == {
        "requestCount": 3,
        "usageRequestCount": 2,
        "missingUsageRequestCount": 1,
        "inputTokens": 14,
        "outputTokens": 5,
        "totalTokens": 19,
        "cachedInputTokens": 0,
        "cacheWriteInputTokens": 0,
        "reasoningOutputTokens": 0,
    }
    assert [entry["ip"] for entry in result["ips"]] == ["10.0.0.2", "10.0.0.3"]
    assert [model["modelId"] for model in result["ips"][0]["models"]] == [
        "public/a",
        "public/b",
    ]
    assert result["ips"][1]["missingUsageRequestCount"] == 1


def test_public_route_records_reported_usage_for_client_ip_and_public_model(tmp_path):
    class Service:
        workspace_root = str(tmp_path)

        @staticmethod
        def authorize(_authorization, _x_api_key):
            return True

        @staticmethod
        def route_metadata(_protocol, _model_id):
            return {
                "providerId": "test-provider",
                "accountId": None,
                "upstreamModel": "upstream-model",
                "providerType": "openai",
                "authMode": "api_key",
            }

        @staticmethod
        def dispatch(_protocol, _payload):
            return GatewayDispatchResult(
                status=200,
                content_type="application/json",
                json_body={
                    "object": "response",
                    "usage": {"input_tokens": 9, "output_tokens": 4, "total_tokens": 13},
                },
            )

        @staticmethod
        def models():
            return {"object": "list", "data": []}

    app = FastAPI()
    register_public_gateway_routes(app, Service())

    response = TestClient(app).post("/v1/responses", json={"model": "public/test"})
    today = datetime.now().astimezone().date().isoformat()
    stats = PublicGatewayUsageStore(str(tmp_path)).aggregate(today)

    assert response.status_code == 200
    assert stats["totals"]["totalTokens"] == 13
    assert stats["ips"][0]["ip"] == "testclient"
    assert stats["ips"][0]["models"][0]["modelId"] == "public/test"


def test_public_stream_records_usage_only_after_normal_completion(tmp_path):
    class Service:
        workspace_root = str(tmp_path)

        @staticmethod
        def authorize(_authorization, _x_api_key):
            return True

        @staticmethod
        def route_metadata(_protocol, _model_id):
            return {
                "providerId": "test-provider",
                "accountId": None,
                "upstreamModel": "upstream-model",
                "providerType": "openai",
                "authMode": "api_key",
            }

        @staticmethod
        def dispatch(_protocol, _payload):
            return GatewayDispatchResult(
                status=200,
                content_type="text/event-stream",
                stream=iter(
                    [
                        b'event: response.completed\ndata: {"type":"response.completed","response":',
                        b'{"usage":{"input_tokens":6,"output_tokens":2,"total_tokens":8}}}\n\n',
                    ]
                ),
            )

        @staticmethod
        def models():
            return {"object": "list", "data": []}

    app = FastAPI()
    register_public_gateway_routes(app, Service())

    response = TestClient(app).post(
        "/v1/responses",
        json={"model": "public/stream", "stream": True},
    )
    today = datetime.now().astimezone().date().isoformat()
    stats = PublicGatewayUsageStore(str(tmp_path)).aggregate(today)

    assert response.status_code == 200
    assert stats["totals"]["totalTokens"] == 8
    assert stats["ips"][0]["models"][0]["modelId"] == "public/stream"


def test_usage_store_rejects_non_iso_date(tmp_path):
    store = PublicGatewayUsageStore(str(tmp_path))

    try:
        store.aggregate("2026/08/26")
    except ValueError as exc:
        assert str(exc) == "Gateway usage date must use YYYY-MM-DD format."
    else:
        raise AssertionError("Expected invalid date to be rejected.")
