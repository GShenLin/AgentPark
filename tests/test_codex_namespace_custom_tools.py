"""Namespace identity must survive custom-tool wrapping in both provider paths."""
import copy
import io
import json

import pytest

from src.cli_provider_runtime.contracts import CodexProtocolError
from src.cli_provider_runtime.doubao_seed_parser import split_seed_calls
from src.cli_provider_runtime.doubao_seed_tools import SeedToolRegistry
from src.cli_provider_runtime.http_transport import UpstreamResponse
from src.cli_provider_runtime.openai_chat_adapter import OpenAIChatAdapter
from src.cli_provider_runtime.responses_conversion import responses_request_to_canonical
from src.cli_provider_runtime.responses_passthrough import ResponsesPassthrough
from src.cli_provider_runtime.responses_wire import tool_call_item


RAW = "text('中文');\ntext('second');"
WRAPPED = json.dumps({"input": RAW}, ensure_ascii=False)


def request():
    return {
        "tools": [{"type": "namespace", "name": "functions", "tools": [
            {"type": "function", "name": "read", "parameters": {"type": "object"}},
            {"type": "custom", "name": "exec", "format": {"type": "text"}},
        ]}],
        "tool_choice": {"type": "custom", "namespace": "functions", "name": "exec"},
        "input": [
            {"type": "custom_tool_call", "namespace": "functions", "name": "exec",
             "call_id": "call-1", "input": RAW},
            {"type": "custom_tool_call_output", "call_id": "call-1", "output": "中文\nsecond"},
        ],
    }


def upstream(events):
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode()
    return UpstreamResponse(200, {"content-type": "text/event-stream"}, io.BytesIO(body))


def payloads(chunks):
    return [json.loads(line[5:]) for line in b"".join(chunks).decode().splitlines()
            if line.startswith("data:")]


def test_chat_custom_namespace_request_history_choice_and_return():
    canonical = responses_request_to_canonical(request(), model="model")
    adapter = OpenAIChatAdapter({"type": "doubao"})
    wire = adapter._payload(canonical, stream=False)
    assert [tool["function"]["name"] for tool in wire["tools"]] == ["functions__read", "functions__exec"]
    assert wire["tool_choice"]["function"]["name"] == "functions__exec"
    call = wire["messages"][0]["tool_calls"][0]
    assert call["id"] == "call-1"
    assert call["function"]["name"] == "functions__exec"
    assert json.loads(call["function"]["arguments"]) == {"input": RAW}
    assert wire["messages"][1]["tool_call_id"] == "call-1"
    restored = tool_call_item(adapter._canonical_call("call-2", "functions__exec", WRAPPED))
    assert restored["type"] == "custom_tool_call"
    assert restored["namespace"] == "functions"
    assert restored["name"] == "exec"
    assert restored["input"] == RAW
    assert restored["call_id"] == "call-2"


def test_chat_stream_reassembles_namespaced_custom_input(monkeypatch):
    canonical = responses_request_to_canonical(request(), model="model")
    chunks = [{"choices": [{"delta": {"tool_calls": [{
        "index": 0, "id": "call-2", "function": {"name": "functions__exec", "arguments": ""},
    }]}}]}]
    chunks.extend({"choices": [{"delta": {"tool_calls": [{
        "index": 0, "function": {"arguments": WRAPPED[pos:pos + 3]},
    }]}}]} for pos in range(0, len(WRAPPED), 3))
    monkeypatch.setattr("src.cli_provider_runtime.openai_chat_adapter.open_json_request",
                        lambda **kwargs: upstream(chunks))
    adapter = OpenAIChatAdapter({"type": "doubao", "baseUrl": "http://example.test", "apiKey": "test"})
    events = payloads(adapter.stream(canonical, response_id="resp-test"))
    item = next(event["item"] for event in events if event["type"] == "response.output_item.done")
    assert (item["type"], item["namespace"], item["name"], item["input"]) == (
        "custom_tool_call", "functions", "exec", RAW)
    assert item["call_id"] == "call-2"
    assert events[-1]["type"] == "response.completed"


@pytest.mark.parametrize(("provider", "embedded"), [
    ("doubao", False), ("doubao", True), ("grok", False), ("grok", True), ("deepseek", False), ("deepseek", True),
])
def test_responses_custom_namespace_roundtrip(provider, embedded):
    original = request()
    if embedded:
        original["input"].insert(0, {"type": "additional_tools", "role": "developer",
                                     "tools": original.pop("tools")})
    untouched = copy.deepcopy(original)
    prepared = ResponsesPassthrough({"type": provider}).prepare_request(original)
    assert original == untouched
    tool = prepared.payload["tools"][1]
    assert tool["name"] == "functions__exec"
    assert prepared.payload["tool_choice"]["name"] == "functions__exec"
    history = prepared.payload["input"][0]
    assert history["name"] == "functions__exec"
    assert "namespace" not in history
    assert history["call_id"] == "call-1"
    if provider in {"doubao", "deepseek", "grok"}:
        assert tool["type"] == "function"
        assert json.loads(history["arguments"]) == {"input": RAW}
        call = {"type": "function_call", "arguments": WRAPPED}
    else:
        assert tool["type"] == "custom"
        assert tool["format"] == {"type": "text"}
        assert history["input"] == RAW
        call = {"type": "custom_tool_call", "input": RAW}
    call.update(name="functions__exec", call_id="call-2")
    restored = ResponsesPassthrough.transform_response({"output": [call]}, prepared.tools_by_wire_name)
    assert restored["output"][0] == {"type": "custom_tool_call", "input": RAW,
                                    "name": "exec", "namespace": "functions", "call_id": "call-2"}


@pytest.mark.parametrize("provider", ["doubao", "deepseek", "grok"])
def test_responses_custom_namespace_stream_preserves_identity_and_hides_wrapper(provider):
    prepared = ResponsesPassthrough({"type": provider}).prepare_request(request())
    item = {"type": "function_call", "id": "fc-2", "call_id": "call-2",
            "name": "functions__exec", "arguments": WRAPPED, "status": "completed"}
    events = [{"type": "response.output_item.added", "item": {**item, "arguments": "", "status": "in_progress"}}]
    events.extend({"type": "response.function_call_arguments.delta", "item_id": "fc-2",
                   "delta": WRAPPED[pos:pos + 3]} for pos in range(0, len(WRAPPED), 3))
    events.extend([
        {"type": "response.function_call_arguments.done", "item_id": "fc-2", "arguments": WRAPPED},
        {"type": "response.output_item.done", "item": item},
        {"type": "response.completed", "response": {"output": [item]}},
    ])
    result = payloads(ResponsesPassthrough.transform_stream(upstream(events), prepared.tools_by_wire_name))
    assert len(result) == 4
    assert result[0]["item"]["namespace"] == "functions"
    assert result[0]["item"]["input"] == ""
    assert result[1]["type"] == "response.custom_tool_call_input.done"
    assert result[1]["input"] == RAW
    assert result[2]["item"]["namespace"] == "functions"
    assert result[2]["item"]["name"] == "exec"
    assert result[2]["item"]["input"] == RAW
    assert result[-1]["response"]["output"][0] == result[2]["item"]


@pytest.mark.parametrize("child", [{"type": "namespace", "name": "nested", "tools": []},
                                   {"type": "tool_search"}, {"type": "unknown"}])
def test_namespace_rejects_unsupported_child_types(child):
    value = request()
    value["tools"][0]["tools"] = [child]
    for convert in [lambda: responses_request_to_canonical(value, model="model"),
                    lambda: ResponsesPassthrough({"type": "grok"}).prepare_request(value)]:
        with pytest.raises(CodexProtocolError, match="function or custom"):
            convert()


@pytest.mark.parametrize("first", [False, True])
def test_flattened_name_collision_is_rejected_in_both_orders(first):
    value = request()
    value["tools"].insert(0 if first else 1, {"type": "custom", "name": "functions__exec"})
    for convert in [lambda: responses_request_to_canonical(value, model="model"),
                    lambda: ResponsesPassthrough({"type": "grok"}).prepare_request(value)]:
        with pytest.raises(CodexProtocolError, match="collide"):
            convert()


def test_same_custom_name_in_different_namespaces_remains_distinct():
    value = request()
    value["tools"].append({"type": "namespace", "name": "other", "tools": [{"type": "custom", "name": "exec"}]})
    prepared = ResponsesPassthrough({"type": "doubao"}).prepare_request(value)
    for namespace in ["functions", "other"]:
        restored = ResponsesPassthrough.transform_response({"type": "function_call",
            "name": namespace + "__exec", "arguments": WRAPPED}, prepared.tools_by_wire_name)
        assert restored["namespace"] == namespace


def test_seed_shell_via_namespaced_executor_keeps_namespace():
    value = request()
    value["tools"][0]["tools"][1]["description"] = "declare const tools: { exec_command(args: { cmd: string }): Promise<unknown>; };"
    _, calls = split_seed_calls('<seed:tool_call><function name="exec_command">'
                               '<parameter name="cmd" string">Write-Output OK</parameter>'
                               '</function></seed:tool_call>')
    call = SeedToolRegistry(value).convert(calls[0])
    assert call["type"] == "custom_tool_call"
    assert call["namespace"] == "functions"
    assert call["name"] == "exec"
    assert "tools.exec_command" in call["input"]


def test_native_openai_preserves_custom_namespace_payload():
    original = request()
    prepared = ResponsesPassthrough({"type": "openai"}).prepare_request(original)
    assert prepared.payload == original
    assert prepared.tools_by_wire_name == {}
