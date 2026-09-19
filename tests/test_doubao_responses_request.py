import copy
import json

import pytest

from src.cli_provider_runtime.contracts import CodexProtocolError
from src.cli_provider_runtime.responses_passthrough import ResponsesPassthrough


def request():
    return {"input": [
        {"type": "additional_tools", "role": "developer", "tools": [
            {"type": "custom", "name": "exec", "description": "Run JS.", "format": {"type": "text"}},
        ]},
        {"type": "message", "role": "user", "content": "Check the folder."},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "I will check."}]},
        {"type": "custom_tool_call", "id": "fc_old", "call_id": "call_old", "name": "exec", "input": 'text("中文");'},
        {"type": "custom_tool_call_output", "call_id": "call_old", "output": [
            {"type": "input_text", "text": "Script completed"}, {"type": "input_text", "text": "中文"},
        ]},
    ], "tool_choice": {"type": "custom", "name": "exec"}}


def test_ark_custom_history_round_trip_preserves_content_and_call_id():
    original = request()
    saved = copy.deepcopy(original)
    prepared = ResponsesPassthrough({"type": "doubao"}).prepare_request(original)
    assert original == saved
    assert prepared.payload["tool_choice"] == {"type": "function", "name": "exec"}
    assert prepared.payload["tools"][0]["type"] == "function"
    assert prepared.payload["input"][:2] == original["input"][1:3]
    call, output = prepared.payload["input"][2:]
    assert call == {"type": "function_call", "call_id": "call_old", "name": "exec", "arguments": '{"input":"text(\\"中文\\");"}'}
    assert output == {"type": "function_call_output", "call_id": "call_old", "output": "Script completed\n中文"}
    response = {"status": "completed", "output": [{**call, "id": "fc_new"}]}
    restored = ResponsesPassthrough.transform_response(response, prepared.tools_by_wire_name, seed_tools=prepared.seed_tools)
    assert restored["output"][0]["type"] == "custom_tool_call"
    assert restored["output"][0]["input"] == 'text("中文");'
    assert "arguments" not in restored["output"][0]


@pytest.mark.parametrize("provider", ["openai", "grok"])
def test_other_providers_keep_custom_history(provider):
    original = request()
    prepared = ResponsesPassthrough({"type": provider}).prepare_request(original)
    assert prepared.payload == original


@pytest.mark.parametrize("arguments", ['{}', '{"input":1}', '{"input":"x","extra":2}', 'bad-json'])
def test_malformed_custom_wrapper_is_not_executable(arguments):
    prepared = ResponsesPassthrough({"type": "doubao"}).prepare_request(request())
    with pytest.raises(CodexProtocolError, match="wrapper"):
        ResponsesPassthrough.transform_response({"output": [{
            "type": "function_call", "name": "exec", "call_id": "call", "arguments": arguments,
        }]}, prepared.tools_by_wire_name)


def test_custom_nontext_result_is_rejected_instead_of_dropped():
    original = request()
    original["input"][-1]["output"].append({"type": "input_image", "image_url": "data:image/png;base64,AAAA"})
    with pytest.raises(CodexProtocolError, match="media mapping"):
        ResponsesPassthrough({"type": "doubao"}).prepare_request(original)
