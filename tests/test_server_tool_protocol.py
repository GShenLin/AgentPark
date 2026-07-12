from src.providers.server_tool_protocol import extract_responses_server_tool_result


def test_extract_responses_server_tool_result_preserves_sources_and_citations():
    raw_response = {
            "id": "resp_1",
            "status": "completed",
            "model": "grok-4.5",
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "output": [
                {
                    "type": "web_search_call",
                    "id": "ws_1",
                    "status": "completed",
                    "action": {
                        "type": "search",
                        "query": "AgentPark",
                        "sources": [
                            {"type": "url", "url": "https://example.com", "title": "Example"}
                        ],
                    },
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "answer",
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "url": "https://example.com",
                                    "title": "Example",
                                    "start_index": 0,
                                    "end_index": 6,
                                }
                            ],
                        }
                    ],
                },
            ]
        }
    result = extract_responses_server_tool_result(raw_response)

    assert result == {
        "server_tool_calls": [
            {
                "call_id": "ws_1",
                "tool_type": "web_search",
                "status": "completed",
                "details": raw_response["output"][0],
                "action": {
                    "type": "search",
                    "query": "AgentPark",
                    "sources": [
                        {"type": "url", "url": "https://example.com", "title": "Example"}
                    ],
                },
                "sources": [{"url": "https://example.com", "title": "Example", "type": "url"}],
            }
        ],
        "citations": [
            {
                "url": "https://example.com",
                "title": "Example",
                "start_index": 0,
                "end_index": 6,
            }
        ],
        "response_metadata": {
            "protocol": "responses",
            "response": {
                "id": "resp_1",
                "status": "completed",
                "model": "grok-4.5",
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            },
            "output_items": raw_response["output"],
        },
    }
