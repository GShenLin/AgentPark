"""A broken final SSE event must not repeat an already executed operation."""
import json
import threading

import pytest

from tests.test_responses_item_runtime_failure import _openai_agent
from src.providers.openai_transport_errors import OpenAITransportError
from src.runtime_cancellation import CancellationRequested


def call_event(call_id="write-1"):
    return {"type": "response.output_item.done", "item": {
        "type": "function_call", "id": "fc-" + call_id, "call_id": call_id,
        "name": "write_file", "arguments": "{}",
    }}


def completed_event(text="done"):
    return {"type": "response.completed", "response": {
        "id": "resp-final", "status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ],
    }}


def run(agent):
    agent.config.update(toolResultSubmissionMaxChars=50000, toolContextCompactionEnabled=False,
                        toolContextCompactionEveryToolCalls=1)
    return agent._send_via_responses(messages=[{"role": "user", "content": "write once"}],
                                    active_tools=[], run_tools=True, reasoning_effort="")


def notices(agent, stage):
    return [json.loads(e["message"]) for e in agent.events if e.get("stage") == stage]


@pytest.mark.parametrize("failure", ["malformed", "eof", "disconnect"])
def test_failed_stream_continues_with_original_result_without_replaying_write(tmp_path, failure):
    agent = _openai_agent()
    agent.config.update(maxRetries=2, toolContextCompactionEnabled=False)
    target = tmp_path / "effects.txt"
    finished = threading.Event()
    requests = []

    def write_file():
        with target.open("a", encoding="utf-8") as f:
            f.write("written\n")
        finished.set()
        return "saved-once"

    agent.tools.function_map["write_file"] = write_file

    def stream(**kwargs):
        payload = json.loads(kwargs["payload_json"])
        requests.append(payload)
        if len(requests) == 1:
            yield json.dumps(call_event())
            assert finished.wait(1)
            if failure == "malformed":
                yield '{"type":"response.completed","response":{"unfinished":"'
            elif failure == "disconnect":
                raise OpenAITransportError("connection closed")
            return
        outputs = [x for x in payload["input"] if x.get("type") == "function_call_output"]
        assert [(x["call_id"], x["output"]) for x in outputs] == [("write-1", "saved-once")]
        assert any("stream failed" in str(x) for x in payload["input"])
        yield json.dumps(completed_event())

    agent._curl_post_sse_data_lines = stream
    assert run(agent) == "done"
    assert len(requests) == 2
    assert target.read_text(encoding="utf-8") == "written\n"
    assert len(notices(agent, "provider_request_completed")) == 1
    assert len(notices(agent, "openai_responses_tool_recovery_ready")) == 1
    assert not notices(agent, "openai_responses_retry")
    attempts = notices(agent, "openai_responses_attempt_finished")
    assert [x["status"] for x in attempts] == ["failed", "completed"]


def test_failure_before_dispatch_can_retry_original_request():
    agent = _openai_agent()
    agent.config.update(maxRetries=1)
    requests = []

    def stream(**kwargs):
        requests.append(kwargs["payload_json"])
        if len(requests) == 1:
            raise OpenAITransportError("handshake failed", retry_scope="request")
        yield json.dumps(completed_event())

    agent._curl_post_sse_data_lines = stream
    assert run(agent) == "done"
    assert requests[0] == requests[1]
    assert len([e for e in agent.events if e.get("stage") == "openai_responses_request_retry"]) == 1


def test_recovery_waits_for_running_tool_and_does_not_dispatch_partial_call():
    agent = _openai_agent()
    agent.config.update(maxRetries=1, toolContextCompactionEnabled=False)
    release, started = threading.Event(), threading.Event()
    requests = []
    count = []

    def write_file():
        count.append(1)
        started.set()
        assert release.wait(2)
        return "saved"

    agent.tools.function_map["write_file"] = write_file

    def stream(**kwargs):
        requests.append(json.loads(kwargs["payload_json"]))
        if len(requests) == 1:
            yield json.dumps(call_event())
            assert started.wait(1)
            yield json.dumps({"type": "response.output_item.added", "item": {
                "type": "function_call", "id": "partial", "name": "write_file"}})
            release.set()
            raise OpenAITransportError("broken")
        assert [x["output"] for x in requests[-1]["input"] if x.get("type") == "function_call_output"] == ["saved"]
        yield json.dumps(completed_event())

    agent._curl_post_sse_data_lines = stream
    assert run(agent) == "done"
    assert count == [1]


def test_exhausted_recovery_budget_preserves_result_and_reports_failure():
    agent = _openai_agent()  # maxRetries=0
    calls = []
    agent.tools.function_map["write_file"] = lambda: calls.append(1) or "saved"

    def stream(**kwargs):
        yield json.dumps(call_event())
        raise OpenAITransportError("broken")

    agent._curl_post_sse_data_lines = stream
    with pytest.raises(RuntimeError, match="recovery budget exhausted"):
        run(agent)
    assert calls == [1]
    assert any(m["role"] == "tool" and m["content"] == "saved" for m in agent.messages)
    assert not notices(agent, "provider_request_completed")


def test_fatal_response_failure_never_continues_after_tool():
    agent = _openai_agent()
    agent.config.update(maxRetries=5)
    calls, requests = [], []
    agent.tools.function_map["write_file"] = lambda: calls.append(1) or "saved"

    def stream(**kwargs):
        requests.append(1)
        yield json.dumps(call_event())
        yield json.dumps({"type": "response.failed", "response": {"id": "fatal", "error": {
            "code": "insufficient_quota", "message": "quota exceeded"}}})

    agent._curl_post_sse_data_lines = stream
    with pytest.raises(RuntimeError, match="not permitted"):
        run(agent)
    assert requests == calls == [1]
    assert not notices(agent, "provider_request_completed")


def test_cancellation_during_recovery_stops_without_replay():
    agent = _openai_agent()
    agent.config.update(maxRetries=1)
    agent.cancel_event = threading.Event()
    release, started = threading.Event(), threading.Event()
    requests = []

    def write_file():
        started.set()
        release.wait(2)
        return "saved"

    agent.tools.function_map["write_file"] = write_file

    def stream(**kwargs):
        requests.append(1)
        yield json.dumps(call_event())
        assert started.wait(1)
        agent.cancel_event.set()
        raise OpenAITransportError("broken")

    agent._curl_post_sse_data_lines = stream
    try:
        with pytest.raises(CancellationRequested):
            run(agent)
        assert requests == [1]
    finally:
        release.set()


def test_text_without_completed_event_is_not_success():
    agent = _openai_agent()
    agent._curl_post_sse_data_lines = lambda **kwargs: iter([
        json.dumps({"type": "response.output_text.delta", "delta": "premature"}),
    ])
    with pytest.raises(RuntimeError, match="without a valid response.completed"):
        run(agent)
    assert not notices(agent, "provider_request_completed")


def test_recovery_budget_is_shared_across_failed_logical_requests():
    agent = _openai_agent()
    agent.config.update(maxRetries=1)
    calls, requests = [], []
    agent.tools.function_map["write_file"] = lambda: calls.append(1) or "saved"

    def stream(**kwargs):
        requests.append(json.loads(kwargs["payload_json"]))
        yield json.dumps(call_event(f"write-{len(requests)}"))
        raise OpenAITransportError("broken")

    agent._curl_post_sse_data_lines = stream
    with pytest.raises(RuntimeError, match="budget exhausted"):
        run(agent)
    assert len(requests) == len(calls) == 2
    assert any(i.get("call_id") == "write-1" and i["type"] == "function_call_output"
               for i in requests[1]["input"])
    assert sum(m["role"] == "tool" and m["content"] == "saved" for m in agent.messages) == 2


def test_broken_stream_is_closed_before_upper_layer_recovery():
    agent = _openai_agent()
    agent.config.update(maxRetries=1)
    closed = threading.Event()
    requests = []
    agent.tools.function_map["write_file"] = lambda: "saved"

    def stream(**kwargs):
        requests.append(1)
        if len(requests) == 1:
            try:
                yield json.dumps(call_event())
                yield '{"type":"response.completed","unfinished":"'
            finally:
                closed.set()
        else:
            assert closed.is_set()
            yield json.dumps(completed_event())

    agent._curl_post_sse_data_lines = stream
    assert run(agent) == "done"
    assert closed.is_set()


def test_recovery_preserves_multiple_results_and_only_current_attempt_reasoning():
    agent = _openai_agent()
    agent.config.update(maxRetries=2, responsesReplayReasoningItems=True)
    requests, effects = [], []
    agent.tools.function_map["write_file"] = lambda: effects.append(1) or "saved"

    def reasoning(identity):
        return {"type": "response.output_item.done", "item": {
            "type": "reasoning", "id": identity, "summary": [], "encrypted_content": identity}}

    def stream(**kwargs):
        requests.append(json.loads(kwargs["payload_json"]))
        if len(requests) == 1:
            yield json.dumps(reasoning("discarded-attempt"))
            raise OpenAITransportError("before tools")
        if len(requests) == 2:
            yield json.dumps(reasoning("current-attempt"))
            yield json.dumps(call_event("first"))
            yield json.dumps(call_event("second"))
            raise OpenAITransportError("after tools")
        items = requests[-1]["input"]
        assert [i["id"] for i in items if i.get("type") == "reasoning"] == ["current-attempt"]
        assert [i["call_id"] for i in items if i.get("type") == "function_call_output"] == ["first", "second"]
        yield json.dumps(completed_event())

    agent._curl_post_sse_data_lines = stream
    assert run(agent) == "done"
    assert len(effects) == 2
    assert len(requests) == 3
