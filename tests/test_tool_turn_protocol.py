import pytest

from src.providers.tool_turn_protocol import prepare_chat_completions_messages


def _assistant_calls(*call_ids):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": f"tool_{call_id}", "arguments": "{}"},
            }
            for call_id in call_ids
        ],
    }


def test_chat_completions_tool_results_are_ordered_by_assistant_call_batch():
    messages = [
        {"role": "user", "content": "run both"},
        _assistant_calls("call-1", "call-2"),
        {"role": "tool", "tool_call_id": "call-2", "content": "second"},
        {"role": "tool", "tool_call_id": "call-1", "content": "first"},
        {"role": "system", "content": "continue"},
    ]

    prepared = prepare_chat_completions_messages(messages)

    assert [message.get("tool_call_id") for message in prepared[2:4]] == ["call-1", "call-2"]
    assert prepared[4] == {"role": "system", "content": "continue"}


def test_chat_completions_rejects_incomplete_parallel_tool_result_batch():
    messages = [
        _assistant_calls("call-1", "call-2"),
        {"role": "tool", "tool_call_id": "call-1", "content": "first"},
    ]

    with pytest.raises(ValueError, match=r"missing=\['call-2'\]"):
        prepare_chat_completions_messages(messages)


def test_chat_completions_rejects_orphan_tool_result():
    with pytest.raises(ValueError, match="immediately follow"):
        prepare_chat_completions_messages(
            [{"role": "tool", "tool_call_id": "call-1", "content": "orphan"}]
        )
