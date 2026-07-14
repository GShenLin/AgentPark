from nodes.agent_message_adapter import build_agent_output_message
from nodes.agent_message_adapter import build_response_metadata_message


def test_build_agent_output_message_preserves_responses_metadata():
    message = build_agent_output_message(
        {
            "response": "answer",
            "server_tool_calls": [{"call_id": "ws_1", "tool_type": "web_search"}],
            "citations": [{"url": "https://example.com"}],
            "response_metadata": {
                "protocol": "responses",
                "response": {"id": "resp_1", "status": "completed"},
                "output_items": [{"type": "web_search_call", "id": "ws_1"}],
            },
        }
    )

    assert message["parts"][0] == {"type": "text", "text": "answer"}
    assert len(message["parts"]) == 1

    metadata = build_response_metadata_message(
        {
            "server_tool_calls": [{"call_id": "ws_1", "tool_type": "web_search"}],
            "citations": [{"url": "https://example.com"}],
            "response_metadata": {
                "protocol": "responses",
                "response": {"id": "resp_1", "status": "completed"},
                "output_items": [{"type": "web_search_call", "id": "ws_1"}],
            },
        },
        scope="final_assistant",
        target_message_id=message["id"],
    )
    assert metadata is not None
    assert metadata["role"] == "metadata"
    assert metadata["parts"][0] == {
        "type": "structured",
        "data": {
            "kind": "response_metadata",
            "scope": "final_assistant",
            "target": {"type": "message", "message_id": message["id"]},
            "server_tool_calls": [{"call_id": "ws_1", "tool_type": "web_search"}],
            "citations": [{"url": "https://example.com"}],
            "response_metadata": {
                "protocol": "responses",
                "response": {"id": "resp_1", "status": "completed"},
                "output_items": [{"type": "web_search_call", "id": "ws_1"}],
            },
            "provider_turn_id": "resp_1",
        },
    }


def test_build_response_metadata_message_preserves_provider_request_totals():
    metadata = build_response_metadata_message(
        {
            "provider_requests": {
                "summaries": [
                    {
                        "request_index": 1,
                        "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
                    }
                ],
                "totals": {
                    "request_count": 1,
                    "completed_request_count": 1,
                    "actual_input_tokens": 100,
                    "actual_output_tokens": 20,
                    "actual_total_tokens": 120,
                },
            }
        },
        scope="agent_run",
        target_message_id="assistant-1",
        fields=("provider_requests",),
    )

    assert metadata is not None
    data = metadata["parts"][0]["data"]
    assert data["provider_requests"]["totals"]["actual_total_tokens"] == 120
    assert data["provider_requests"]["summaries"][0]["usage"]["output_tokens"] == 20
    assert data["scope"] == "agent_run"
    assert data["target"] == {"type": "message", "message_id": "assistant-1"}
