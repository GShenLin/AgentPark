from src.providers.provider_request_summary import build_provider_request_summary


def test_provider_request_summary_counts_tool_call_and_result_chars():
    summary = build_provider_request_summary(
        request_index=1,
        request_api="chat_completions",
        current_input=[
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "function": {"name": "read_file", "arguments": '{"path":"README.md"}'},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": "file body",
            },
        ],
        tools_payload=[],
        stream=True,
        responses_mode="",
        requested_responses_mode="",
    )

    assert summary["tool_call_chars_by_call"][0]["call_id"] == "call-1"
    assert summary["tool_call_chars_by_call"][0]["name"] == "read_file"
    assert summary["tool_call_chars_total"] > 0
    assert summary["tool_result_chars_total"] > 0


def test_provider_request_summary_estimates_ascii_and_non_ascii_without_tokenizer():
    ascii_summary = build_provider_request_summary(
        request_index=1,
        request_api="responses",
        current_input=[{"role": "user", "content": "a" * 400}],
        tools_payload=[],
        stream=True,
        responses_mode="",
        requested_responses_mode="",
    )
    cjk_summary = build_provider_request_summary(
        request_index=1,
        request_api="responses",
        current_input=[{"role": "user", "content": "中" * 400}],
        tools_payload=[],
        stream=True,
        responses_mode="",
        requested_responses_mode="",
    )

    assert ascii_summary["approx_input_tokens"] < cjk_summary["approx_input_tokens"]
    assert ascii_summary["approx_input_tokens"] > 0
    assert cjk_summary["approx_input_tokens"] >= 400
