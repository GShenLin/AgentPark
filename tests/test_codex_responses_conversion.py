import json
from unittest.mock import ANY

import pytest

from src.codex_runtime.anthropic_adapter import _tool_choice as anthropic_tool_choice
from src.codex_runtime.gemini_adapter import _tool_choice as gemini_tool_choice
from src.codex_runtime.openai_chat_adapter import OpenAIChatAdapter
from src.codex_runtime.openai_chat_adapter import _chat_tool_choice
from src.codex_runtime.provider_adapter import provider_protocol
from src.codex_runtime.contracts import CodexProtocolError
from src.codex_runtime.responses_conversion import responses_request_to_canonical
from src.codex_runtime.responses_conversion import tool_call_item


def test_responses_custom_tool_round_trip_through_chat_wrapper():
    request = responses_request_to_canonical(
        {
            "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "edit"}]}],
            "tools": [
                {
                    "type": "custom",
                    "name": "apply_patch",
                    "description": "Apply a patch",
                    "format": {"type": "grammar", "syntax": "lark", "definition": "start: /.+/"},
                }
            ],
            "stream": True,
        },
        model="mock-model",
    )

    assert request.tools[0].kind == "custom"
    adapter = OpenAIChatAdapter({"baseUrl": "http://example.test/v1", "apiKey": "secret"})
    adapter._tools_by_wire = {request.tools[0].wire_name: request.tools[0]}
    call = adapter._canonical_call("call-1", "apply_patch", json.dumps({"input": "*** Begin Patch"}))

    assert call.kind == "custom"
    assert call.arguments == "*** Begin Patch"


def test_tool_choice_objects_are_supported_without_unhashable_errors():
    choice = {"type": "custom", "name": "apply_patch"}

    assert _chat_tool_choice(choice) == {"type": "function", "function": {"name": "apply_patch"}}
    assert anthropic_tool_choice(choice, True)["name"] == "apply_patch"
    assert gemini_tool_choice(choice)["allowedFunctionNames"] == ["apply_patch"]


def test_namespace_tools_are_flattened_for_chat_and_restored_for_codex():
    request = responses_request_to_canonical(
        {
            "input": "search",
            "tools": [
                {
                    "type": "namespace",
                    "name": "docs",
                    "description": "Documentation tools",
                    "tools": [
                        {
                            "type": "function",
                            "name": "search",
                            "description": "Search docs",
                            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}},
                        }
                    ],
                }
            ],
        },
        model="mock-model",
    )
    tool = request.tools[0]
    adapter = OpenAIChatAdapter({"baseUrl": "http://example.test/v1", "apiKey": "secret"})
    payload = adapter._payload(request, stream=False)
    call = adapter._canonical_call("call-1", "docs__search", '{"query":"Codex"}')

    assert tool.namespace == "docs"
    assert payload["tools"][0]["function"]["name"] == "docs__search"
    assert call.name == "search"
    assert call.namespace == "docs"


def test_responses_lite_additional_tools_become_chat_tools_not_messages():
    request = responses_request_to_canonical(
        {
            "model": "codex-runtime-model",
            "input": [
                {
                    "type": "additional_tools",
                    "role": "developer",
                    "tools": [
                        {
                            "type": "function",
                            "name": "shell_command",
                            "description": "Run a shell command.",
                            "parameters": {
                                "type": "object",
                                "properties": {"command": {"type": "string"}},
                                "required": ["command"],
                            },
                        }
                    ],
                },
                {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "Use tools when needed."}],
                },
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Inspect the workspace."}],
                },
            ],
            "stream": True,
        },
        model="provider-model",
    )

    assert request.model == "provider-model"
    assert [tool.wire_name for tool in request.tools] == ["shell_command"]
    assert [message.role for message in request.messages] == ["system", "user"]
    assert request.messages[0].content == "Use tools when needed."
    assert request.messages[1].content == "Inspect the workspace."


def test_responses_lite_additional_tools_requires_instruction_role():
    with pytest.raises(CodexProtocolError, match="additional_tools role"):
        responses_request_to_canonical(
            {
                "input": [
                    {"type": "additional_tools", "role": "user", "tools": []},
                    {"type": "message", "role": "user", "content": "hello"},
                ]
            },
            model="provider-model",
        )


def test_tool_search_round_trip_through_chat_transport():
    request = responses_request_to_canonical(
        {
            "input": [
                {"type": "message", "role": "user", "content": "Find a calendar tool."},
                {
                    "type": "tool_search_call",
                    "call_id": "search-1",
                    "status": "completed",
                    "execution": "client",
                    "arguments": {"query": "calendar create", "limit": 1},
                },
                {
                    "type": "tool_search_output",
                    "call_id": "search-1",
                    "status": "completed",
                    "execution": "client",
                    "tools": [{"type": "function", "name": "calendar_create", "parameters": {}}],
                },
            ],
            "tools": [
                {
                    "type": "tool_search",
                    "execution": "client",
                    "description": "Search deferred tools.",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}, "limit": {"type": "number"}},
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                }
            ],
        },
        model="mock-model",
    )

    assert request.tools[0].kind == "tool_search"
    assert request.messages[1].tool_calls[0].kind == "tool_search"
    assert json.loads(str(request.messages[2].content))["tools"][0]["name"] == "calendar_create"

    adapter = OpenAIChatAdapter({"baseUrl": "http://example.test/v1", "apiKey": "secret"})
    adapter._tools_by_wire = {request.tools[0].wire_name: request.tools[0]}
    call = adapter._canonical_call("search-2", "tool_search", '{"query":"drive files"}')

    assert call.kind == "tool_search"
    assert tool_call_item(call) == {
        "type": "tool_search_call",
        "id": ANY,
        "call_id": "search-2",
        "status": "completed",
        "execution": "client",
        "arguments": {"query": "drive files"},
    }


def test_tool_search_chat_conversion_rejects_server_execution():
    with pytest.raises(CodexProtocolError, match="execution='client'"):
        responses_request_to_canonical(
            {
                "input": "search",
                "tools": [
                    {
                        "type": "tool_search",
                        "execution": "server",
                        "description": "Server-side search.",
                        "parameters": {"type": "object"},
                    }
                ],
            },
            model="mock-model",
        )


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({"type": "openai", "responsesApi": True}, "responses"),
        ({"type": "grok", "responsesApi": True}, "responses"),
        ({"type": "doubao", "responsesApi": True}, "responses"),
        ({"type": "openai", "responsesApi": False}, "openai_chat"),
        ({"type": "deepseek"}, "openai_chat"),
        ({"type": "kimi"}, "openai_chat"),
        ({"type": "zhipu"}, "openai_chat"),
        ({"type": "claude"}, "anthropic"),
        ({"type": "gemini"}, "gemini"),
    ],
)
def test_provider_protocol_is_not_restricted_to_openai(config, expected):
    assert provider_protocol(config) == expected
