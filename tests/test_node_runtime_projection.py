import json

from src.web_backend.node_runtime_projection import load_node_runtime_projection


def test_node_runtime_projection_restores_provider_summary_from_runtime_log(tmp_path):
    summary = {
        "request_index": 3,
        "request_api": "chat_completions",
        "input_item_count": 2,
        "approx_input_chars": 1200,
        "approx_input_tokens": 300,
        "tool_call_chars_total": 40,
        "tool_result_chars_total": 500,
    }
    event = {
        "type": "runtime_notice",
        "source": "provider_runtime",
        "stage": "provider_request_summary",
        "message": json.dumps(summary, ensure_ascii=False),
        "provider": "unit",
    }
    (tmp_path / "runtime_events.jsonl").write_text(
        json.dumps(
            {
                "event": "runtime_notice",
                "runtime_event": event,
                "provider_request_summary": summary,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    projection = load_node_runtime_projection(str(tmp_path))

    assert projection["last_runtime_event"]["stage"] == "provider_request_summary"
    assert projection["provider_request_summaries"][0]["approx_input_chars"] == 1200
    assert projection["provider_request_totals"]["request_count"] == 1
    assert projection["provider_request_totals"]["tool_result_chars"] == 500


def test_node_runtime_projection_restores_completed_request_usage(tmp_path):
    summary = {
        "request_index": 1,
        "request_api": "responses",
        "approx_input_tokens": 90,
    }
    completion = {
        "request_index": 1,
        "request_api": "responses",
        "usage": {"input_tokens": 100, "output_tokens": 25, "total_tokens": 125},
    }
    records = [
        {
            "event": "runtime_notice",
            "runtime_event": {
                "type": "runtime_notice",
                "source": "provider_runtime",
                "stage": "provider_request_summary",
                "message": json.dumps(summary),
            },
            "provider_request_summary": summary,
        },
        {
            "event": "runtime_notice",
            "runtime_event": {
                "type": "runtime_notice",
                "source": "provider_runtime",
                "stage": "provider_request_completed",
                "message": json.dumps(completion),
            },
            "provider_request_completion": completion,
        },
    ]
    (tmp_path / "runtime_events.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    projection = load_node_runtime_projection(str(tmp_path))

    assert projection["provider_request_summaries"][0]["usage"]["total_tokens"] == 125
    assert projection["provider_request_totals"]["completed_request_count"] == 1
    assert projection["provider_request_totals"]["actual_total_tokens"] == 125
