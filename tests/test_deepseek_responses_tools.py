import copy

import pytest

from src.cli_provider_runtime.contracts import CodexProtocolError
from src.cli_provider_runtime.responses_passthrough import ResponsesPassthrough


def test_deepseek_embedded_tools_merge_and_media_results_survive():
    image = {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}
    original = {"tools": [{"type": "function", "name": "read", "parameters": {"type": "object"}}],
        "input": [{"type": "additional_tools", "role": "developer", "tools": [
            {"type": "custom", "name": "exec", "format": {"type": "text"}}]},
            {"type": "custom_tool_call", "call_id": "c1", "name": "exec", "input": "capture()"},
            {"type": "custom_tool_call_output", "call_id": "c1", "output": [image]}]}
    saved = copy.deepcopy(original)
    prepared = ResponsesPassthrough({"type": "deepseek"}).prepare_request(original)
    assert original == saved
    assert [tool["name"] for tool in prepared.payload["tools"]] == ["read", "exec"]
    assert all(tool["type"] == "function" for tool in prepared.payload["tools"])
    assert prepared.payload["input"][-1] == {
        "type": "function_call_output", "call_id": "c1", "output": [image]}
    assert prepared.seed_tools is None


def test_deepseek_does_not_execute_dsml_from_plain_text():
    text = '<｜｜DSML｜｜ calls><｜｜DSML｜｜ invoke name="exec">code</｜｜DSML｜｜ invoke></｜｜DSML｜｜ calls>'
    response = {"output": [{"type": "message", "role": "assistant", "content": [
        {"type": "output_text", "text": text}]}]}
    assert ResponsesPassthrough.transform_response(response, {}) == response


@pytest.mark.parametrize("role", ["user", "assistant", None])
def test_deepseek_rejects_non_instruction_tool_declarations(role):
    with pytest.raises(CodexProtocolError, match="instruction role"):
        ResponsesPassthrough({"type": "deepseek"}).prepare_request({"input": [
            {"type": "additional_tools", "role": role, "tools": []}]})
