from __future__ import annotations

from copy import deepcopy
import json

import pytest

from src.providers.provider_errors import ProviderProtocolError
from src.providers.tool_call_runtime import ToolCallExecutionRuntime
from src.providers.zhipu_agent import ZhipuAgent
from src.providers.zhipu_chat_runtime import ZhipuChatRuntime
from src.providers.zhipu_tool_schema_adapter import ZHIPU_REF_PROPERTY_ALIAS
from src.providers.zhipu_tool_schema_adapter import adapt_zhipu_tool_declarations
from src.providers.zhipu_tool_schema_adapter import restore_zhipu_tool_call_arguments
from src.tool.base_tool import BaseTool
from src.tool.workspace_exec_tools import workspace_exec_declaration


def _make_zhipu_agent():
    agent = ZhipuAgent.__new__(ZhipuAgent)
    agent.config = {
        "apiKey": "test-key",
        "baseUrl": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-test",
        "maxRetries": 0,
        "retryDelaySec": 0,
        "timeoutMs": 1000,
        "toolContextCompactionEnabled": False,
        "toolContextCompactionEveryToolCalls": 1,
    }
    agent.provider_name = "zhipu"
    agent.messages = []
    agent.tools = BaseTool(agent)
    agent.system_prompt = None
    agent.internal_memory_enabled = False
    agent.tool_event_callback = None
    agent._service_targets_cache = (
        ToolCallExecutionRuntime(agent),
        ZhipuChatRuntime(agent),
    )
    agent._read_provider_config_from_file = lambda: dict(agent.config)
    agent._get_messages_with_memory = lambda: list(agent.messages)
    agent.Message = lambda role, content, persist=True, **kwargs: agent.messages.append(
        {"role": role, "content": content, **kwargs}
    )
    return agent


def _property_names(value):
    names = []
    if isinstance(value, list):
        for item in value:
            names.extend(_property_names(item))
        return names
    if not isinstance(value, dict):
        return names
    properties = value.get("properties")
    if isinstance(properties, dict):
        names.extend(properties.keys())
    for item in value.values():
        names.extend(_property_names(item))
    return names


def test_zhipu_tool_adapter_aliases_reserved_ref_without_mutating_workspace_tool():
    original = deepcopy(workspace_exec_declaration)

    adaptation = adapt_zhipu_tool_declarations([workspace_exec_declaration])

    assert workspace_exec_declaration == original
    assert adaptation.aliased_tool_names == frozenset({"workspace_exec"})
    adapted = adaptation.declarations[0]
    parameters = adapted["function"]["parameters"]
    assert "$ref" not in _property_names(parameters)
    assert ZHIPU_REF_PROPERTY_ALIAS in _property_names(parameters)
    assert ZHIPU_REF_PROPERTY_ALIAS in adapted["function"]["description"]
    assert "$ref" not in adapted["function"]["description"]


def test_zhipu_tool_adapter_restores_nested_reference_arguments():
    tool_calls = [
        {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "workspace_exec",
                "arguments": json.dumps(
                    {
                        "stages": [
                            {
                                "id": "inspect",
                                "operations": [
                                    {
                                        "id": "read",
                                        "kind": "read_file",
                                        "arguments": {
                                            "file_path": {
                                                ZHIPU_REF_PROPERTY_ALIAS: "list",
                                                "path": ["result", "files", 0],
                                            }
                                        },
                                    }
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            },
        }
    ]

    restored = restore_zhipu_tool_call_arguments(
        tool_calls,
        aliased_tool_names=frozenset({"workspace_exec"}),
    )

    arguments = json.loads(restored[0]["function"]["arguments"])
    reference = arguments["stages"][0]["operations"][0]["arguments"]["file_path"]
    assert reference == {"$ref": "list", "path": ["result", "files", 0]}
    assert json.loads(tool_calls[0]["function"]["arguments"])["stages"][0]["operations"][0]["arguments"][
        "file_path"
    ] == {ZHIPU_REF_PROPERTY_ALIAS: "list", "path": ["result", "files", 0]}


def test_zhipu_send_adapts_schema_and_restores_returned_tool_call():
    agent = _make_zhipu_agent()
    agent.messages = [{"role": "user", "content": "inspect"}]
    captured = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "workspace_exec",
                                    "arguments": json.dumps(
                                        {
                                            "stages": [
                                                {
                                                    "id": "second",
                                                    "operations": [
                                                        {
                                                            "id": "read",
                                                            "kind": "read_file",
                                                            "arguments": {
                                                                "file_path": {
                                                                    ZHIPU_REF_PROPERTY_ALIAS: "first",
                                                                    "path": ["result", "files", 0],
                                                                }
                                                            },
                                                        }
                                                    ],
                                                }
                                            ]
                                        }
                                    ),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }

    agent._stream_chat_completions_with_retry = fake_stream

    result = agent.Send(tools=[workspace_exec_declaration], run_tools=False, stream=True)

    sent_tool = json.loads(captured["payload_json"])["tools"][0]
    assert "$ref" not in _property_names(sent_tool["function"]["parameters"])
    returned_arguments = json.loads(result["tool_calls"][0]["function"]["arguments"])
    assert returned_arguments["stages"][0]["operations"][0]["arguments"]["file_path"]["$ref"] == "first"


def test_zhipu_stream_surfaces_top_level_provider_error_event():
    agent = _make_zhipu_agent()
    event = {
        "error": {
            "code": "InternalServiceError",
            "message": "The service encountered an unexpected internal error. Request id: request-123",
            "param": "",
            "type": "InternalServerError",
        }
    }
    agent._curl_post_sse_data_lines = lambda **_kwargs: iter([json.dumps(event), "[DONE]"])

    with pytest.raises(ProviderProtocolError) as exc_info:
        agent._stream_chat_completions_once(
            url="https://example.test/chat/completions",
            headers={},
            payload_json="{}",
            stream_handler=None,
        )

    message = str(exc_info.value)
    assert "zhipu_chat_completions_stream provider error" in message
    assert "code=InternalServiceError" in message
    assert "type=InternalServerError" in message
    assert "request-123" in message


def test_zhipu_tool_adapter_rejects_alias_collision():
    declaration = {
        "type": "function",
        "function": {
            "name": "conflict",
            "parameters": {
                "type": "object",
                "properties": {
                    "$ref": {"type": "string"},
                    ZHIPU_REF_PROPERTY_ALIAS: {"type": "string"},
                },
            },
        },
    }

    with pytest.raises(ValueError, match="alias collision"):
        adapt_zhipu_tool_declarations([declaration])
