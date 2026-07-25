from __future__ import annotations

import json
import urllib.request
from types import SimpleNamespace

from claude_agent_sdk import AssistantMessage
from claude_agent_sdk import StreamEvent
from claude_agent_sdk import TextBlock
from claude_agent_sdk import ToolResultBlock
from claude_agent_sdk import ToolUseBlock
from claude_agent_sdk import UserMessage

from nodes.claude_node.runtime.live_bridge import ClaudeLiveBridge
from nodes.claude_node.runtime.messages_conversion import messages_request_to_canonical
from nodes.claude_node.runtime.provider_gateway import ClaudeProviderGateway
from nodes.claude_node.runtime.session_projection import project_session_records
from src.cli_provider_runtime.contracts import CanonicalResult
from src.cli_provider_runtime.responses_wire import canonical_result_sse


def test_messages_conversion_preserves_system_images_and_tool_transcript():
    request = messages_request_to_canonical(
        {
            "model": "requested-model",
            "system": [{"type": "text", "text": "top-level"}],
            "messages": [
                {"role": "system", "content": "message-level"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "inspect"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "AA==",
                            },
                        },
                    ],
                },
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call-1",
                            "name": "Read",
                            "input": {"file_path": "setup.py"},
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call-1",
                            "content": "contents",
                        }
                    ],
                },
            ],
            "tools": [
                {
                    "name": "Read",
                    "description": "Read a file",
                    "input_schema": {"type": "object"},
                }
            ],
            "stream": True,
            "max_tokens": 128,
        },
        model="provider-model",
    )

    assert request.model == "provider-model"
    assert [message.role for message in request.messages] == [
        "system",
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assert isinstance(request.messages[2].content, list)
    assert request.messages[2].content[1]["image_url"]["url"] == "data:image/png;base64,AA=="
    assert request.messages[3].tool_calls[0].name == "Read"
    assert request.messages[4].tool_call_id == "call-1"


def test_live_bridge_projects_partial_text_and_tool_events_without_duplication():
    events: list[dict] = []
    tool_events: list[dict] = []
    bridge = ClaudeLiveBridge(events.append, tool_event_callback=tool_events.append)

    bridge.handle(
        StreamEvent(
            uuid="stream-1",
            session_id="session-1",
            event={
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "id": "call-1", "name": "Read"},
            },
            parent_tool_use_id=None,
        )
    )
    bridge.handle(
        AssistantMessage(
            content=[ToolUseBlock(id="call-1", name="Read", input={"file_path": "setup.py"})],
            model="claude-test",
            parent_tool_use_id=None,
        )
    )
    bridge.handle(
        UserMessage(
            content=[ToolResultBlock(tool_use_id="call-1", content="contents", is_error=False)],
            uuid="user-2",
            parent_tool_use_id=None,
        )
    )
    bridge.handle(
        StreamEvent(
            uuid="stream-2",
            session_id="session-1",
            event={
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "Done"},
            },
            parent_tool_use_id=None,
        )
    )
    bridge.handle(
        AssistantMessage(
            content=[TextBlock(text="Done")],
            model="claude-test",
            parent_tool_use_id=None,
        )
    )
    structured = bridge.emit_done("Done")

    assert [event["type"] for event in tool_events] == ["tool_call_start", "tool_call_end"]
    assert tool_events[1]["arguments"] == {"file_path": "setup.py"}
    assert bridge.text == "Done"
    assert [event["type"] for event in events].count("node_message_delta") == 1
    assert structured["response_metadata"]["claude_session_id"] == "session-1"
    assert structured["response_metadata"]["runtime_tool_calls"][0]["status"] == "completed"


def test_session_projection_maps_native_claude_tool_history_to_memory():
    messages = [
        SimpleNamespace(
            type="user",
            uuid="user-1",
            message={"role": "user", "content": "Read the file"},
        ),
        SimpleNamespace(
            type="assistant",
            uuid="assistant-1",
            message={
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "Read",
                        "input": {"file_path": "setup.py"},
                    }
                ],
            },
        ),
        SimpleNamespace(
            type="user",
            uuid="user-2",
            message={
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-1",
                        "content": "contents",
                    }
                ],
            },
        ),
        SimpleNamespace(
            type="assistant",
            uuid="assistant-2",
            message={"role": "assistant", "content": [{"type": "text", "text": "Done"}]},
        ),
    ]

    records = project_session_records(messages)

    assert [record["role"] for record in records] == ["user", "tool", "assistant"]
    tool = records[1]["parts"][0]
    assert tool["name"] == "Read"
    assert tool["args"] == {"file_path": "setup.py"}
    assert tool["result_preview"] == "contents"


def test_provider_gateway_serves_claude_messages_over_canonical_adapter(monkeypatch):
    captured = {}

    class Adapter:
        @staticmethod
        def stream(request):
            captured["reasoning_effort"] = request.reasoning_effort
            return canonical_result_sse(
                CanonicalResult(
                    response_id="resp-1",
                    text="GATEWAY_OK",
                    input_tokens=3,
                    output_tokens=2,
                )
            )

    monkeypatch.setattr(
        "nodes.claude_node.runtime.provider_gateway.ConfigLoader",
        lambda: SimpleNamespace(
            get_provider_config=lambda _provider_id: {
                "model": "provider-model",
                "supportmode": ["chat"],
                "type": "openai",
            }
        ),
    )
    monkeypatch.setattr(
        "nodes.claude_node.runtime.provider_gateway.provider_protocol",
        lambda _config: "openai_chat",
    )
    monkeypatch.setattr(
        "nodes.claude_node.runtime.provider_gateway.create_chat_adapter",
        lambda _config: Adapter(),
    )
    gateway = ClaudeProviderGateway()
    lease = gateway.register("provider-a", reasoning_effort="low")
    try:
        payload = json.dumps(
            {
                "model": "requested",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
                "max_tokens": 32,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{lease.base_url}/v1/messages",
            data=payload,
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            body = response.read().decode("utf-8")
    finally:
        gateway.release(lease.token)
        gateway.close()

    assert "event: message_start" in body
    assert '"text":"GATEWAY_OK"' in body
    assert '"output_tokens":2' in body
    assert captured["reasoning_effort"] == "low"
