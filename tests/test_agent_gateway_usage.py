from __future__ import annotations

from nodes.agent_gateway_usage import build_agent_gateway_usage_recorder
from src.providers.provider_request_usage import ProviderRequestTracker
from src.public_gateway.usage_stats import PublicGatewayUsageStore


def test_provider_request_tracker_forwards_completion_with_request_api():
    captured = []
    tracker = ProviderRequestTracker(on_completion=lambda completion: captured.append(completion))
    summary = {"request_index": 1, "request_api": "responses"}
    tracker.record_summary(summary)

    completion = tracker.record_completion(1, {})

    assert completion == {"request_index": 1, "request_api": "responses"}
    assert captured == [completion]


def test_agent_gateway_usage_recorder_groups_local_node_usage_by_ip_and_model(tmp_path):
    recorder = build_agent_gateway_usage_recorder(
        workspace_root=str(tmp_path),
        client_ip="127.0.0.1",
        task_id="trace-1",
        model_id="gpt-test",
    )
    assert recorder is not None
    completion = {
        "request_index": 1,
        "request_api": "responses",
        "usage": {"input_tokens": 187, "output_tokens": 14, "total_tokens": 201},
    }

    recorder(completion)
    recorder(completion)

    usage_root = tmp_path / ".runtime" / "public-gateway-usage"
    date_text = next(usage_root.glob("*.jsonl")).stem
    stats = PublicGatewayUsageStore(str(tmp_path)).aggregate(date_text)

    assert stats["totals"]["requestCount"] == 1
    assert stats["totals"]["totalTokens"] == 201
    assert stats["ips"][0]["ip"] == "127.0.0.1"
    assert stats["ips"][0]["models"][0]["modelId"] == "gpt-test"


def test_agent_gateway_usage_recorder_requires_real_request_attribution(tmp_path):
    assert build_agent_gateway_usage_recorder(
        workspace_root=str(tmp_path),
        client_ip="",
        task_id="trace-1",
        model_id="gpt-test",
    ) is None
