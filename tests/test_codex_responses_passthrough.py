from __future__ import annotations

import io
import json

from src.codex_runtime.http_transport import UpstreamResponse
from src.codex_runtime.responses_passthrough import ResponsesPassthrough


def _request() -> dict:
    return {
        "model": "model",
        "input": [
            {
                "type": "function_call",
                "call_id": "call-1",
                "namespace": "workspace",
                "name": "read",
                "arguments": "{}",
            },
            {"type": "function_call_output", "call_id": "call-1", "output": "done"},
        ],
        "tools": [
            {
                "type": "namespace",
                "name": "workspace",
                "description": "Workspace tools",
                "tools": [
                    {
                        "type": "function",
                        "name": "read",
                        "description": "Read a file",
                        "parameters": {"type": "object", "properties": {}},
                    }
                ],
            },
            {
                "type": "custom",
                "name": "apply_patch",
                "description": "Apply patch",
                "format": {"type": "grammar", "syntax": "lark", "definition": "start: /.+/"},
            },
        ],
        "tool_choice": {"type": "function", "namespace": "workspace", "name": "read"},
        "reasoning": {"effort": "high", "summary": "auto"},
        "client_metadata": {"session_id": "session-1"},
        "stream": True,
    }


def test_doubao_responses_flattens_namespace_tools_and_history():
    original = _request()
    prepared = ResponsesPassthrough({"type": "doubao"}).prepare_request(original)

    assert original["tools"][0]["type"] == "namespace"
    assert prepared.payload["tools"][0]["type"] == "function"
    assert prepared.payload["tools"][0]["name"] == "workspace__read"
    assert prepared.payload["tools"][1]["type"] == "custom"
    assert prepared.payload["tool_choice"] == {"type": "function", "name": "workspace__read"}
    assert prepared.payload["input"][0]["name"] == "workspace__read"
    assert "namespace" not in prepared.payload["input"][0]
    assert prepared.payload["reasoning"] == {"effort": "high"}
    assert "client_metadata" not in prepared.payload


def test_openai_responses_keeps_native_namespace_tools():
    prepared = ResponsesPassthrough({"type": "openai"}).prepare_request(_request())

    assert prepared.payload["tools"][0]["type"] == "namespace"
    assert prepared.payload["reasoning"] == {"effort": "high", "summary": "auto"}
    assert prepared.payload["client_metadata"] == {"session_id": "session-1"}
    assert prepared.tools_by_wire_name == {}


def test_responses_complete_restores_namespace_tool_identity():
    prepared = ResponsesPassthrough({"type": "doubao"}).prepare_request(_request())
    response = {
        "id": "resp-1",
        "output": [
            {
                "type": "function_call",
                "call_id": "call-2",
                "name": "workspace__read",
                "arguments": '{"path":"README.md"}',
            }
        ],
    }

    restored = ResponsesPassthrough.transform_response(response, prepared.tools_by_wire_name)

    assert restored["output"][0]["name"] == "read"
    assert restored["output"][0]["namespace"] == "workspace"
    assert "namespace" not in response["output"][0]


def test_responses_stream_restores_namespace_in_nested_output_items():
    prepared = ResponsesPassthrough({"type": "doubao"}).prepare_request(_request())
    event = {
        "type": "response.output_item.done",
        "item": {
            "type": "function_call",
            "call_id": "call-2",
            "name": "workspace__read",
            "arguments": "{}",
        },
    }
    body = (
        "event: response.output_item.done\r\n"
        f"data: {json.dumps(event)}\r\n"
        "\r\n"
        "data: [DONE]\r\n"
        "\r\n"
    ).encode("utf-8")
    response = UpstreamResponse(
        status=200,
        headers={"content-type": "text/event-stream"},
        body=io.BytesIO(body),
    )

    output = b"".join(ResponsesPassthrough.transform_stream(response, prepared.tools_by_wire_name))
    frames = [frame for frame in output.decode("utf-8").split("\r\n\r\n") if frame]
    payload = json.loads(next(line[6:] for line in frames[0].splitlines() if line.startswith("data: ")))

    assert frames[0].splitlines()[0] == "event: response.output_item.done"
    assert payload["item"]["name"] == "read"
    assert payload["item"]["namespace"] == "workspace"
    assert frames[1] == "data: [DONE]"
