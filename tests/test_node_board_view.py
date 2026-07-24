import json

from src.web_backend.node_board_view import build_board_provider_summary, build_node_board_view


def _provider_summary() -> dict:
    return {
        "request_index": 4,
        "request_api": "responses",
        "input_item_count": 80,
        "approx_input_chars": 400_000,
        "approx_input_tokens": 100_000,
        "environment_context_chars": 12_000,
        "input_items": [{"index": index, "text": "x" * 1000} for index in range(80)],
        "tool_call_chars_total": 20_000,
        "tool_result_chars_total": 300_000,
        "tool_result_chars_by_call": [
            {"call_id": f"call-{index}", "name": "read_file", "chars": 10_000}
            for index in range(30)
        ],
        "largest_tool_result": {
            "call_id": "call-29",
            "name": "read_file",
            "chars": 10_000,
            "status": "completed",
            "text": "x" * 20_000,
        },
        "tools_included": [{"name": f"tool-{index}", "schema": "x" * 1000} for index in range(20)],
        "tools_included_count": 20,
    }


def test_board_provider_summary_is_an_explicit_small_display_contract():
    summary = build_board_provider_summary(_provider_summary())

    assert summary["request_api"] == "responses"
    assert summary["tool_result_count"] == 30
    assert summary["largest_tool_result"] == {
        "call_id": "call-29",
        "name": "read_file",
        "chars": 10_000,
        "status": "completed",
    }
    assert "input_items" not in summary
    assert "tools_included" not in summary


def test_board_view_preserves_card_diagnostics_without_shipping_tool_payloads():
    provider_summary = _provider_summary()
    config = {
        "node_id": "Agent",
        "state": "working",
        "last_runtime_event": {
            "type": "runtime_notice",
            "stage": "provider_request_summary",
            "source": "provider_runtime",
            "message": json.dumps(provider_summary),
        },
        "runtime_events": [
            {
                "type": "runtime_notice",
                "stage": "node_run_start",
                "source": "node_runtime",
                "message": '{"status":"running","started_at_epoch_ms":1}',
            },
            {
                "type": "tool_call_end",
                "call_id": "call-1",
                "name": "read_file",
                "result_preview": "x" * 50_000,
            },
            {
                "type": "runtime_notice",
                "stage": "provider_request_summary",
                "source": "provider_runtime",
                "message": json.dumps(provider_summary),
            },
        ],
        "runtime_tool_calls": [
            {
                "call_id": "call-1",
                "name": "read_file",
                "status": "completed",
                "arguments": {"content": "x" * 50_000},
                "result_preview": "x" * 50_000,
                "result_chars": 200_000,
            }
        ],
        "provider_request_summaries": [provider_summary],
        "provider_request_totals": {"request_count": 4, "actual_total_tokens": 120_000},
    }

    board = build_node_board_view(config)

    assert [event["stage"] for event in board["runtime_events"]] == [
        "node_run_start",
        "provider_request_summary",
    ]
    assert board["runtime_tool_calls"] == [
        {
            "call_id": "call-1",
            "name": "read_file",
            "status": "completed",
            "result_chars": 200_000,
        }
    ]
    assert board["provider_request_totals"]["request_count"] == 4
    assert "completed_requests" not in board
    assert "last_completed_request" not in board
    assert len(json.dumps(board, ensure_ascii=False)) < len(json.dumps(config, ensure_ascii=False)) / 10


def test_board_view_limits_last_message_to_card_preview_contract():
    board = build_node_board_view({"node_id": "Agent", "last_message": "x" * 2_000})

    assert board["node_id"] == "Agent"
    assert board["last_message"] == "x" * 512
