import copy
import io
import json

import pytest

from src.cli_provider_runtime.contracts import CodexProtocolError
from src.cli_provider_runtime.http_transport import UpstreamResponse
from src.cli_provider_runtime.responses_passthrough import ResponsesPassthrough


RAW = ('检查。<seed:tool_call><function name="exec_command">'
       '<parameter name="cmd" string">Write-Output \'你好\'</parameter></function></seed:tool_call>')
REQUEST = {"tools": [{"type": "function", "name": "exec_command", "parameters": {
    "type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"], "additionalProperties": False,
}}]}


def frames(text=RAW, *, terminal="response.completed", item_done=True):
    item = {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text}]}
    yield {"type": "response.created", "response": {"id": "resp_1", "status": "in_progress"}}
    yield {"type": "response.output_item.added", "output_index": 0, "item": {**item, "status": "in_progress", "content": []}}
    base = {"item_id": "msg_1", "output_index": 0, "content_index": 0}
    yield {"type": "response.content_part.added", **base, "part": {"type": "output_text", "text": ""}}
    for char in text:
        yield {"type": "response.output_text.delta", **base, "delta": char}
    yield {"type": "response.output_text.done", **base, "text": text}
    yield {"type": "response.content_part.done", **base, "part": item["content"][0]}
    if item_done:
        yield {"type": "response.output_item.done", "output_index": 0, "item": item}
    if terminal:
        yield {"type": terminal, "response": {"id": "resp_1", "status": terminal.removeprefix("response."),
               "output": [item], "output_text": text, "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}}}


def transform(events, provider="doubao"):
    prepared = ResponsesPassthrough({"type": provider}).prepare_request(REQUEST)
    body = ''.join('event: ' + event["type"] + '\r\ndata: ' + json.dumps(event, ensure_ascii=False) + '\r\n\r\n' for event in events).encode()
    upstream = UpstreamResponse(200, {"content-type": "text/event-stream"}, io.BytesIO(body))
    stream = ResponsesPassthrough.transform_stream(upstream, prepared.tools_by_wire_name, seed_tools=prepared.seed_tools)
    return upstream, stream


def decode(stream):
    return [json.loads(next(line[5:] for line in chunk.decode().splitlines() if line.startswith("data:"))) for chunk in stream]


@pytest.mark.parametrize("item_done", [True, False])
def test_split_marker_is_removed_everywhere_and_tool_ids_are_consistent(item_done):
    upstream, stream = transform(frames(item_done=item_done))
    output = decode(stream)
    assert upstream.body.closed
    assert "<seed:tool_call>" not in json.dumps(output)
    assert ''.join(event.get("delta", "") for event in output if event["type"] == "response.output_text.delta") == "检查。"
    calls = [event["item"] for event in output if event["type"] == "response.output_item.done" and event["item"]["type"] == "function_call"]
    assert len(calls) == 1
    assert json.loads(calls[0]["arguments"]) == {"cmd": "Write-Output '你好'"}
    assert output[-1]["response"]["output"][-1] == calls[0]
    assert output[-1]["response"]["usage"]["total_tokens"] == 30
    assert [event["sequence_number"] for event in output] == list(range(len(output)))
    assert output[-2]["output_index"] == 1


@pytest.mark.parametrize("terminal", ["response.failed", "response.incomplete"])
def test_failed_or_incomplete_stream_never_emits_converted_tools(terminal):
    _, stream = transform(frames(terminal=terminal))
    output = decode(stream)
    assert not any(event.get("item", {}).get("type") == "function_call" for event in output)
    assert output[-1]["type"] == terminal


def test_disconnect_raises_and_closes_upstream_without_emitting_calls():
    upstream, stream = transform(frames(terminal=""))
    emitted = []
    with pytest.raises(CodexProtocolError, match="terminal"):
        for chunk in stream:
            emitted.extend(decode([chunk]))
    assert upstream.body.closed
    assert not any(event.get("item", {}).get("type") == "function_call" for event in emitted)


def test_complete_response_reuses_stream_call_ids_without_duplicate_execution():
    _, stream = transform(frames())
    output = decode(stream)
    added = [e["item"] for e in output if e["type"] == "response.output_item.added" and e["item"]["type"] == "function_call"]
    done = [e["item"] for e in output if e["type"] == "response.output_item.done" and e["item"]["type"] == "function_call"]
    assert len(added) == len(done) == 1
    assert added[0]["call_id"] == done[0]["call_id"] == output[-1]["response"]["output"][-1]["call_id"]


@pytest.mark.parametrize("text", ["普通回答", "```xml\n" + RAW + "\n```"])
def test_plain_text_and_code_examples_retain_original_events(text):
    original = list(frames(text))
    _, stream = transform(original)
    output = decode(stream)
    for event in output:
        event.pop("sequence_number")
    assert output == original


@pytest.mark.parametrize("provider", ["openai", "grok"])
def test_other_providers_do_not_execute_seed_text(provider):
    original = list(frames())
    _, stream = transform(original, provider)
    assert decode(stream) == original


def test_invalid_call_does_not_leak_marker_or_execute():
    upstream, stream = transform(frames(RAW.replace('name="exec_command"', 'name="not_registered"')))
    emitted = []
    with pytest.raises(CodexProtocolError, match="undeclared"):
        for chunk in stream:
            emitted.extend(decode([chunk]))
    assert "<seed:tool_call>" not in json.dumps(emitted)
    assert upstream.body.closed


def test_changed_terminal_snapshot_is_an_error():
    events = list(frames())
    events[-1] = copy.deepcopy(events[-1])
    events[-1]["response"]["output"][0]["content"][0]["text"] = "different"
    _, stream = transform(events)
    with pytest.raises(CodexProtocolError, match="changed"):
        list(stream)


def test_nonstreamed_response_uses_same_provider_scoped_adapter():
    prepared = ResponsesPassthrough({"type": "doubao"}).prepare_request(REQUEST)
    payload = list(frames())[-1]["response"]
    result = ResponsesPassthrough.transform_response(payload, prepared.tools_by_wire_name, seed_tools=prepared.seed_tools)
    assert result["output_text"] == "检查。"
    assert result["output"][-1]["type"] == "function_call"


def test_reasoning_keeps_its_index_and_generated_calls_follow_message():
    events = list(frames())
    reasoning = {"type": "reasoning", "id": "reasoning_1", "summary": [{"type": "summary_text", "text": "plan"}]}
    for event in events:
        if "output_index" in event:
            event["output_index"] += 1
    events[1:1] = [
        {"type": "response.output_item.added", "output_index": 0, "item": {**reasoning, "summary": []}},
        {"type": "response.reasoning_summary_text.delta", "item_id": "reasoning_1", "output_index": 0, "summary_index": 0, "delta": "plan"},
        {"type": "response.output_item.done", "output_index": 0, "item": reasoning},
    ]
    events[-1]["response"]["output"].insert(0, reasoning)
    _, stream = transform(events)
    output = decode(stream)
    done = [event for event in output if event["type"] == "response.output_item.done"]
    assert [event["output_index"] for event in done] == [0, 1, 2]
    assert output[2]["type"] == "response.reasoning_summary_text.delta"
    assert output[-1]["response"]["output"][0] == reasoning


def test_native_tool_response_passes_through_without_seed_conversion():
    item = {"type": "function_call", "id": "fc_native", "call_id": "call_native", "name": "exec_command",
            "arguments": '{"cmd":"echo native"}', "status": "completed"}
    events = [
        {"type": "response.created", "response": {"id": "resp_1"}},
        {"type": "response.output_item.done", "output_index": 0, "item": item},
        {"type": "response.completed", "response": {"id": "resp_1", "status": "completed", "output": [item]}},
    ]
    _, stream = transform(events)
    output = decode(stream)
    for event in output:
        event.pop("sequence_number")
    assert output == events


def test_repeated_terminal_event_cannot_emit_calls_twice():
    events = list(frames())
    events.append(events[-1])
    _, stream = transform(events)
    emitted = []
    with pytest.raises(CodexProtocolError, match="after its terminal"):
        for chunk in stream:
            emitted.extend(decode([chunk]))
    assert sum(event.get("item", {}).get("type") == "function_call" and event["type"] == "response.output_item.done" for event in emitted) == 1
