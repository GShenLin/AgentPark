import json

from src.codex_runtime.live_bridge import CodexLiveBridge


def test_codex_live_bridge_preserves_message_thinking_and_tool_event_contracts():
    events = []
    bridge = CodexLiveBridge(events.append)

    bridge.handle(
        {
            "method": "item/reasoning/summaryTextDelta",
            "params": {"itemId": "reason-1", "delta": "Inspecting"},
        }
    )
    bridge.handle(
        {
            "method": "item/started",
            "params": {
                "item": {
                    "type": "commandExecution",
                    "id": "cmd-1",
                    "command": "python --version",
                    "cwd": "D:/Project/AgentPark",
                    "status": "inProgress",
                }
            },
        }
    )
    bridge.handle(
        {
            "method": "item/commandExecution/outputDelta",
            "params": {"itemId": "cmd-1", "delta": "Python 3.13"},
        }
    )
    bridge.handle(
        {
            "method": "item/completed",
            "params": {
                "item": {
                    "type": "commandExecution",
                    "id": "cmd-1",
                    "command": "python --version",
                    "cwd": "D:/Project/AgentPark",
                    "status": "completed",
                    "aggregatedOutput": "Python 3.13",
                    "durationMs": 12,
                }
            },
        }
    )
    bridge.handle({"method": "item/agentMessage/delta", "params": {"delta": "Done"}})
    structured = bridge.emit_done("Done")

    assert events[0] == {
        "type": "node_thinking_delta",
        "delta": "Inspecting",
        "text": "Inspecting",
        "provider": "codex",
    }
    assert events[1]["type"] == "tool_call_start"
    assert events[1]["name"] == "shell_command"
    assert events[2]["type"] == "tool_call_end"
    assert events[2]["result_preview"] == "Python 3.13"
    assert events[3] == {"type": "node_message_delta", "delta": "Done", "text": "Done"}
    assert events[4]["type"] == "node_message_done"
    assert structured["response_metadata"]["runtime_tool_calls"][0]["call_id"] == "cmd-1"


def test_codex_live_bridge_maps_file_change_and_mcp_items_to_existing_tool_events():
    events = []
    bridge = CodexLiveBridge(events.append)

    for item in (
        {
            "type": "fileChange",
            "id": "patch-1",
            "status": "completed",
            "changes": [{"path": "src/app.py", "kind": "update", "diff": "large diff"}],
        },
        {
            "type": "mcpToolCall",
            "id": "mcp-1",
            "server": "docs",
            "tool": "search",
            "status": "completed",
            "arguments": {"query": "Codex"},
            "result": {"content": [{"type": "text", "text": "result"}]},
        },
    ):
        bridge.handle({"method": "item/completed", "params": {"item": item}})

    assert [event["type"] for event in events] == [
        "tool_call_start",
        "tool_call_end",
        "tool_call_start",
        "tool_call_end",
    ]
    assert events[0]["name"] == "apply_patch"
    assert events[0]["arguments"] == {"changes": [{"path": "src/app.py", "kind": "update"}]}
    assert events[2]["name"] == "docs.search"


def test_codex_live_bridge_projects_each_raw_response_usage_as_one_model_turn():
    events = []
    bridge = CodexLiveBridge(events.append, provider_id="GPT_Official")

    bridge.handle(
        {
            "method": "rawResponse/completed",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "responseId": "resp-1",
                "usage": {
                    "inputTokens": 120,
                    "cachedInputTokens": 80,
                    "cacheWriteInputTokens": 4,
                    "outputTokens": 30,
                    "reasoningOutputTokens": 10,
                    "totalTokens": 150,
                },
            },
        }
    )

    notices = [event for event in events if event.get("type") == "runtime_notice"]
    assert [event["stage"] for event in notices] == [
        "provider_request_summary",
        "provider_request_completed",
    ]
    assert all(event["provider"] == "GPT_Official" for event in notices)
    assert json.loads(notices[0]["message"])["request_index"] == 1
    completion = json.loads(notices[1]["message"])
    assert completion == {
        "request_api": "responses",
        "request_index": 1,
        "response_id": "resp-1",
        "usage": {
            "cache_write_input_tokens": 4,
            "cached_input_tokens": 80,
            "input_tokens": 120,
            "output_tokens": 30,
            "reasoning_output_tokens": 10,
            "total_tokens": 150,
        },
    }
    assert bridge.structured_result()["response_metadata"]["provider_requests"] == [completion]


def test_codex_live_bridge_projects_provider_gateway_request_diagnostics():
    events = []
    bridge = CodexLiveBridge(events.append, provider_id="GPT_Official")
    observation = {
        "request_index": 1,
        "provider_id": "GPT_Official",
        "requested_model": "codex-runtime",
        "provider_model": "gpt-provider",
        "payload_chars": 200,
        "tools_included_count": 7,
    }

    bridge.handle({"method": "agentpark/providerGateway/request", "params": observation})

    assert json.loads(events[0]["message"]) == observation
    assert events[0]["stage"] == "provider_gateway_request"
    assert bridge.structured_result()["response_metadata"]["provider_gateway_requests"] == [observation]


def test_codex_live_bridge_uses_thread_token_usage_when_raw_events_are_unavailable():
    events = []
    bridge = CodexLiveBridge(events.append, provider_id="GPT_Official")

    bridge.handle(
        {
            "method": "thread/tokenUsage/updated",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "tokenUsage": {
                    "last": {
                        "inputTokens": 41,
                        "cachedInputTokens": 20,
                        "outputTokens": 7,
                        "reasoningOutputTokens": 2,
                        "totalTokens": 48,
                    },
                    "total": {
                        "inputTokens": 141,
                        "cachedInputTokens": 80,
                        "outputTokens": 17,
                        "reasoningOutputTokens": 5,
                        "totalTokens": 158,
                    },
                },
            },
        }
    )

    completed = [
        json.loads(event["message"])
        for event in events
        if event.get("stage") == "provider_request_completed"
    ]
    assert completed == [
        {
            "request_api": "responses",
            "request_index": 1,
            "usage": {
                "cached_input_tokens": 20,
                "input_tokens": 41,
                "output_tokens": 7,
                "reasoning_output_tokens": 2,
                "total_tokens": 48,
            },
        }
    ]


def test_codex_live_bridge_does_not_double_count_token_update_after_raw_response():
    events = []
    bridge = CodexLiveBridge(events.append, provider_id="GPT_Official")
    usage = {
        "inputTokens": 41,
        "cachedInputTokens": 20,
        "outputTokens": 7,
        "reasoningOutputTokens": 2,
        "totalTokens": 48,
    }

    bridge.handle(
        {
            "method": "rawResponse/completed",
            "params": {"responseId": "resp-1", "usage": usage},
        }
    )
    bridge.handle(
        {
            "method": "thread/tokenUsage/updated",
            "params": {"tokenUsage": {"last": usage, "total": usage}},
        }
    )

    assert len(bridge.provider_requests) == 1


def test_codex_live_bridge_projects_raw_custom_tool_items():
    events = []
    bridge = CodexLiveBridge(events.append)

    bridge.handle({
        "method": "rawResponseItem/completed",
        "params": {
            "item": {
                "type": "custom_tool_call",
                "call_id": "call-exec-1",
                "name": "exec",
                "input": "text('ok');",
            }
        },
    })
    bridge.handle({
        "method": "rawResponseItem/completed",
        "params": {
            "item": {
                "type": "custom_tool_call_output",
                "call_id": "call-exec-1",
                "output": [{"type": "input_text", "text": "ok"}],
            }
        },
    })

    starts = [event for event in events if event.get("type") == "tool_call_start"]
    ends = [event for event in events if event.get("type") == "tool_call_end"]
    assert starts == [
        {
            "type": "tool_call_start",
            "name": "exec",
            "call_id": "call-exec-1",
            "provider": "codex",
            "arguments": {"input": "text('ok');"},
            "status": "running",
        }
    ]
    assert len(ends) == 1
    assert ends[0]["name"] == "exec"
    assert ends[0]["call_id"] == "call-exec-1"
    assert ends[0]["status"] == "completed"
    assert "ok" in ends[0]["result_preview"]

