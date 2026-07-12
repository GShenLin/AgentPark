from src.providers.provider_request_usage import ProviderRequestTracker
from src.providers.provider_request_usage import extract_provider_usage


def test_extract_provider_usage_normalizes_openai_details():
    usage = extract_provider_usage(
        {
            "usage": {
                "input_tokens": 120,
                "output_tokens": 30,
                "total_tokens": 150,
                "input_tokens_details": {"cached_tokens": 80},
                "output_tokens_details": {"reasoning_tokens": 12},
            }
        }
    )

    assert usage == {
        "input_tokens": 120,
        "output_tokens": 30,
        "total_tokens": 150,
        "cached_input_tokens": 80,
        "reasoning_output_tokens": 12,
    }


def test_extract_provider_usage_normalizes_anthropic_cache_tokens():
    usage = extract_provider_usage(
        {
            "usage": {
                "input_tokens": 200,
                "output_tokens": 40,
                "cache_read_input_tokens": 150,
                "cache_creation_input_tokens": 20,
            }
        }
    )

    assert usage == {
        "input_tokens": 200,
        "output_tokens": 40,
        "total_tokens": 240,
        "cached_input_tokens": 150,
        "cache_write_input_tokens": 20,
    }


def test_provider_request_tracker_accumulates_full_turn_actual_usage():
    tracker = ProviderRequestTracker()
    tracker.record_summary({"request_index": 1, "approx_input_tokens": 90})
    tracker.record_completion(1, {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
    tracker.record_summary({"request_index": 2, "approx_input_tokens": 140})
    tracker.record_completion(
        2,
        {
            "input_tokens": 150,
            "output_tokens": 30,
            "total_tokens": 180,
            "cached_input_tokens": 70,
        },
    )

    snapshot = tracker.snapshot()

    assert snapshot["summaries"][0]["usage"]["total_tokens"] == 120
    assert snapshot["summaries"][1]["usage"]["cached_input_tokens"] == 70
    assert snapshot["totals"]["request_count"] == 2
    assert snapshot["totals"]["completed_request_count"] == 2
    assert snapshot["totals"]["actual_input_tokens"] == 250
    assert snapshot["totals"]["actual_output_tokens"] == 50
    assert snapshot["totals"]["actual_total_tokens"] == 300
    assert snapshot["totals"]["actual_cached_input_tokens"] == 70
