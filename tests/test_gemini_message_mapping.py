from src.providers.gemini_message_mapping import attach_gemini_call_ids
from src.providers.gemini_message_mapping import map_messages_to_gemini


def test_gemini_parallel_function_responses_are_grouped_and_matched_by_id():
    raw_parts = [
        {
            "functionCall": {"id": "call-1", "name": "first", "args": {}},
            "thoughtSignature": "signature-1",
        },
        {"functionCall": {"id": "call-2", "name": "second", "args": {}}},
    ]
    assistant_parts = attach_gemini_call_ids(raw_parts, ["call-1", "call-2"])
    messages = [
        {"role": "user", "content": "run both"},
        {"role": "assistant", "content": None, "parts": assistant_parts},
        {
            "role": "function",
            "tool_call_id": "call-2",
            "name": "second",
            "content": '{"value":2}',
        },
        {
            "role": "function",
            "tool_call_id": "call-1",
            "name": "first",
            "content": '{"value":1}',
        },
    ]

    system, contents = map_messages_to_gemini(messages)

    assert system is None
    assert contents[1] == {"role": "model", "parts": raw_parts}
    assert contents[2] == {
        "role": "user",
        "parts": [
            {
                "functionResponse": {
                    "id": "call-1",
                    "name": "first",
                    "response": {"value": 1},
                }
            },
            {
                "functionResponse": {
                    "id": "call-2",
                    "name": "second",
                    "response": {"value": 2},
                }
            },
        ],
    }


def test_gemini_internal_id_does_not_mutate_legacy_wire_function_call():
    raw_parts = [{"functionCall": {"name": "legacy", "args": {}}}]
    assistant_parts = attach_gemini_call_ids(raw_parts, ["gemini-generated-id"])

    _, contents = map_messages_to_gemini(
        [
            {"role": "assistant", "parts": assistant_parts},
            {
                "role": "function",
                "tool_call_id": "gemini-generated-id",
                "name": "legacy",
                "content": "ok",
            },
        ]
    )

    assert contents[0] == {"role": "model", "parts": raw_parts}
    assert contents[1]["parts"][0]["functionResponse"] == {
        "name": "legacy",
        "response": {"result": "ok"},
    }
