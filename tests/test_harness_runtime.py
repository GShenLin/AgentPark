from __future__ import annotations

import json
import sys
import threading
import time

import pytest

from src.harness.adapters.deepseek_harness import DeepSeekEvents, resume_models
from src.harness.adapters.pi import PiEvents
from src.harness.adapters.openclaw import parse_result
from src.harness.events import HarnessEvents
from src.harness.process import run_process
from src.runtime_cancellation import CancellationRequested


def test_pi_native_events_project_tools_and_reject_failed_assistant():
    emitted = []
    events = HarnessEvents("pi", "p", emitted.append)
    parser = PiEvents(events)
    for event in [
        {"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "Hello"}},
        {"type": "tool_execution_start", "toolCallId": "call1", "toolName": "read", "args": {"path": "x"}},
        {"type": "tool_execution_end", "toolCallId": "call1", "toolName": "read", "result": {"text": "data"}},
        {"type": "message_end", "message": {"role": "assistant", "stopReason": "stop", "content": [{"type": "text", "text": "Done"}]}},
    ]:
        parser.handle(json.dumps(event))
    assert parser.final_text == "Done"
    result = events.done(parser.final_text)
    assert [item["type"] for item in emitted] == ["node_message_delta", "tool_call_start", "tool_call_end", "node_message_done"]
    assert result.metadata["response_metadata"]["runtime_tool_calls"][0]["name"] == "read"
    with pytest.raises(RuntimeError, match="Pi failed"):
        parser.handle(json.dumps({"type": "message_end", "message": {"role": "assistant", "stopReason": "error", "errorMessage": "upstream failed"}}))


def test_deepseek_acp_validates_session_and_text_contract():
    events = HarnessEvents("deepseek_harness", "p", None)
    parser = DeepSeekEvents(events)
    parser.handle({"sessionId": "session-123", "update": {"sessionUpdate": "config_option_update"}})
    parser.bind("session-123")
    parser.handle({"sessionId": "session-123", "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "hello"}}})
    assert events.text == "hello"
    with pytest.raises(ValueError, match="different session"):
        parser.handle({"sessionId": "other", "update": {}})
    with pytest.raises(ValueError, match="text response"):
        parser.handle({"sessionId": "session-123", "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "image"}}})


def test_deepseek_resume_keeps_historical_model_descriptors(tmp_path):
    settings = tmp_path / "settings.yaml"
    assert resume_models(settings, "first") == [{"id": "first"}]
    settings.write_text(json.dumps({"llm-pi-ai": {"providers": {"agentpark": {
        "models": [{"id": "first"}, {"id": "second"}]}}}}), encoding="utf-8")
    assert resume_models(settings, "third") == [{"id": "first"}, {"id": "second"}, {"id": "third"}]
    assert resume_models(settings, "first") == [{"id": "first"}, {"id": "second"}]
    settings.write_text('{"llm-pi-ai": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid DeepSeek"):
        resume_models(settings, "first")


def test_openclaw_accepts_only_local_payload_contract():
    assert parse_result('{"payloads":[{"text":"hello"},{"text":"world"}]}') == "hello\nworld"
    with pytest.raises(ValueError):
        parse_result('{"result":"unstructured"}')
    with pytest.raises(RuntimeError):
        parse_result('{"payloads":[]}')


def test_process_reads_utf8_stdin_and_surfaces_exit_error(tmp_path):
    assert run_process([sys.executable, "-c", "import sys; print(sys.stdin.read())"], cwd=str(tmp_path),
                       stdin="中文\nline", env={**__import__('os').environ, "PYTHONIOENCODING": "utf-8"}).strip() == "中文\nline"
    with pytest.raises(RuntimeError, match="specific failure"):
        run_process([sys.executable, "-c", "import sys; sys.stderr.write('specific failure'); sys.exit(4)"], cwd=str(tmp_path))


def test_process_cancellation_and_timeout(tmp_path):
    cancel = threading.Event()
    timer = threading.Timer(0.25, cancel.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(CancellationRequested):
            run_process([sys.executable, "-c", "import time; time.sleep(30)"], cwd=str(tmp_path), cancel_source=cancel)
    finally:
        timer.cancel()
    assert time.monotonic() - started < 5
    with pytest.raises(TimeoutError):
        run_process([sys.executable, "-c", "import time; time.sleep(30)"], cwd=str(tmp_path), timeout=0.2)
