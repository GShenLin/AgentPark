from __future__ import annotations

import json
import sys

import pytest

from src.harness.adapters.openclaw_progress import OpenClawProgress, PREFIX
from src.harness.events import HarnessEvents
from src.harness.process import run_process


def send(parser, stream, data, seq, run="run-one"):
    parser.handle_stderr(PREFIX + json.dumps({"type": "event", "event": {
        "runId": run, "seq": seq, "stream": stream, "data": data}}))


def setup():
    received = []
    events = HarnessEvents("openclaw", "provider", received.append)
    parser = OpenClawProgress(events)
    parser.handle_stderr(PREFIX + '{"type":"ready","version":1}')
    return parser, events, received


def test_native_progress_projects_text_thinking_tools_and_status():
    parser, events, received = setup()
    parser.handle_stderr("ordinary CLI diagnostic\n")
    send(parser, "lifecycle", {"phase": "start"}, 1)
    send(parser, "thinking", {"delta": "Considering"}, 2)
    send(parser, "assistant", {"delta": "Reading file."}, 3)
    send(parser, "tool", {"phase": "start", "name": "read", "toolCallId": "1", "args": {"path": "a.txt"}}, 4)
    send(parser, "tool", {"phase": "update", "name": "read", "toolCallId": "1", "partialResult": "working"}, 5)
    send(parser, "tool", {"phase": "result", "name": "read", "toolCallId": "1", "isError": False,
                          "result": {"content": [{"type": "text", "text": "file content"}]}}, 6)
    send(parser, "compaction", {"phase": "start"}, 7)
    send(parser, "lifecycle", {"phase": "end"}, 8)
    parser.finish()
    result = events.done("Final answer")
    assert events.text == "Reading file." and events.thinking == "Considering"
    tool = result.metadata["response_metadata"]["runtime_tool_calls"][0]
    assert tool["status"] == "completed" and "file content" in tool["result_preview"]
    assert any(item["type"] == "node_thinking_delta" for item in received)
    assert any(item.get("stage") == "openclaw_tool_update" for item in received)
    assert received[-1]["type"] == "node_message_done"


def test_distinct_runs_can_reuse_native_tool_ids_and_surface_errors():
    parser, events, received = setup()
    for run in ("parent", "child"):
        send(parser, "tool", {"phase": "start", "name": "exec", "toolCallId": "1", "args": {}}, 1, run)
        send(parser, "tool", {"phase": "result", "name": "exec", "toolCallId": "1", "isError": True,
                              "result": "command failed"}, 2, run)
    parser.finish()
    assert len(events.tools) == 2
    assert all(tool["status"] == "failed" for tool in events.tools.values())


def test_streaming_write_arguments_precede_execution_without_starting_tool():
    parser, events, received = setup()
    for sequence in (1, 2):
        send(parser, "tool", {"phase": "input_delta", "name": "write", "toolCallId": "edit-1",
                              "diff": {"added": sequence, "removed": 0}}, sequence)
    assert events.started == {} and events.tools == {}
    assert received[-1]["stage"] == "openclaw_tool_input"
    assert received[-1]["call_id"] == "run-one:edit-1"
    assert "+2 / -0" in received[-1]["name"]
    send(parser, "tool", {"phase": "start", "name": "write", "toolCallId": "edit-1",
                          "args": {"path": "a.txt", "content": "one\ntwo\n"}}, 3)
    send(parser, "tool", {"phase": "result", "name": "write", "toolCallId": "edit-1",
                          "isError": False, "result": "Written"}, 4)
    parser.finish()
    assert len(events.tools) == 1
    assert sum(event["type"] == "tool_call_start" for event in received) == 1


@pytest.mark.parametrize("diff", [None, {}, {"added": -1, "removed": 0},
                                   {"added": True, "removed": 0}, {"added": 1, "removed": "0"}])
def test_input_delta_rejects_invalid_counters(diff):
    parser, _, _ = setup()
    with pytest.raises(ValueError, match="diff counters"):
        send(parser, "tool", {"phase": "input_delta", "name": "write", "toolCallId": "1", "diff": diff}, 1)


def test_tool_review_reports_status_without_creating_an_execution():
    parser, events, received = setup()
    for sequence, status in enumerate(("in_progress", "approved", "denied", "aborted"), 1):
        send(parser, "tool", {"phase": "review", "name": "exec", "toolCallId": "1",
                              "review": {"id": "guardian:1", "status": status}}, sequence)
    parser.finish()
    assert not events.tools
    assert received[-1]["stage"] == "openclaw_tool_review"
    assert received[-1]["name"] == "exec: review aborted"


def test_missing_bridge_invalid_order_and_incomplete_calls_fail_explicitly():
    with pytest.raises(RuntimeError, match="did not load"):
        OpenClawProgress(HarnessEvents("openclaw", "p", None)).finish()
    parser, _, _ = setup()
    send(parser, "assistant", {"delta": "Hi"}, 1)
    with pytest.raises(ValueError, match="ordered"):
        send(parser, "assistant", {"delta": "Hi"}, 1)
    with pytest.raises(ValueError, match="requires string"):
        send(parser, "assistant", {"text": "no delta"}, 2)
    send(parser, "tool", {"phase": "start", "name": "read", "toolCallId": "1", "args": {}}, 3)
    with pytest.raises(RuntimeError, match="unfinished"):
        parser.finish()


def test_stderr_frames_are_complete_and_drained_after_stdout_closes(tmp_path):
    frames = []
    script = "import sys; print('result', flush=True); sys.stdout.close(); sys.stderr.write('x'*20000+'\\n'); sys.stderr.flush()"
    result = run_process([sys.executable, "-c", script], cwd=str(tmp_path), on_stderr_line=frames.append)
    assert result.strip() == "result" and frames == ["x" * 20000 + "\n"]


def test_stderr_callback_failure_stops_child(tmp_path):
    def fail(line):
        raise ValueError("invalid progress")
    with pytest.raises(ValueError, match="invalid progress"):
        run_process([sys.executable, "-c", "import sys,time; print('event',file=sys.stderr,flush=True); time.sleep(30)"],
                    cwd=str(tmp_path), on_stderr_line=fail, timeout=5)
