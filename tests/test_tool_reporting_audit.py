"""Regression coverage for timers underneath the common tool execution layer."""
from contextlib import asynccontextmanager
import json
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from src.tool.base_tool import BaseTool
from src.tool.tool_tasks import tool_task_scope


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


def test_ask_user_reports_then_accepts_answer_on_the_same_dialog(tmp_path, monkeypatch):
    from src import user_interaction_store as store
    monkeypatch.setattr(store, "get_memories_root", lambda: str(tmp_path))
    agent = SimpleNamespace(config={}, tool_event_callback=lambda event: None)
    with tool_task_scope(agent):
        tools = BaseTool(agent)
        tools.addTool("user_interaction_tools")
        first = decode(tools.execute_tool("ask_user", {"title": "Review", "timeout_sec": 1}))
        assert first["status"] == "running"
        request_id = first["progress"]["request_id"]
        assert store.read_interaction_request(request_id)["status"] == "pending"
        again = decode(tools.execute_tool("wait_tool_task", {"task_id": first["task_id"], "wait_seconds": .01}))
        assert again["status"] == "running" and again["next_report_at"]
        assert len(store.list_interaction_requests()) == 1
        store.submit_interaction_response(request_id, {"values": {"message": "yes"}})
        final = decode(tools.execute_tool("wait_tool_task", {"task_id": first["task_id"], "wait_seconds": 2}))
        assert final["status"] == "completed" and final["values"] == {"message": "yes"}


def test_parallel_dispatch_does_not_discard_tasks_at_old_batch_deadline():
    from src.base_agent import BaseAgent
    owner = SimpleNamespace(_resolve_parallel_workers=lambda count: 2,
                            _get_provider_config=lambda: {"toolWorkerTimeoutSec": .001})
    seen = []
    barrier = threading.Barrier(2)
    def execute(value):
        barrier.wait(timeout=2)
        time.sleep(.03)
        seen.append(value)
        return value
    result = BaseAgent._execute_tasks_parallel_ordered(owner, [1, 2], execute)
    assert result == [1, 2] and sorted(seen) == [1, 2]


@pytest.mark.parametrize("transport", ["stdio", "sse", "streamable-http"])
@pytest.mark.parametrize("tool_execution", [False, True])
def test_mcp_session_timer_is_only_used_for_discovery(monkeypatch, transport, tool_execution):
    # These async fakes do not perform I/O. Drive the coroutine directly so this
    # contract test does not need an event loop or a listening network socket.
    import mcp
    import mcp.client.stdio
    import mcp.client.sse
    import mcp.client.streamable_http
    from nodes.agent_mcp_loader import McpServerDefinition
    from nodes.agent_mcp_runtime import McpServerClient
    captured = {}
    class Session:
        def __init__(self, *args, **kwargs):
            captured["session"] = kwargs
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def initialize(self):
            pass
    @asynccontextmanager
    async def stream(*args, **kwargs):
        captured["transport"] = kwargs
        yield (None, None, None) if transport == "streamable-http" else (None, None)
    monkeypatch.setattr(mcp, "ClientSession", Session)
    monkeypatch.setattr(mcp.client.stdio, "stdio_client", stream)
    monkeypatch.setattr(mcp.client.sse, "sse_client", stream)
    monkeypatch.setattr(mcp.client.streamable_http, "streamablehttp_client", stream)
    server = McpServerDefinition("test", "Test", {"transport": transport, "command": "test",
        "url": "http://example.test/mcp", "readTimeoutSeconds": 10, "sseReadTimeout": 20})
    async def operation(session):
        return "done"
    coroutine = McpServerClient(server)._with_session(operation, tool_execution=tool_execution)
    with pytest.raises(StopIteration) as stopped:
        coroutine.send(None)
    assert stopped.value.value == "done"
    timer = captured["session"]["read_timeout_seconds"]
    assert timer is None if tool_execution else timer.total_seconds() == 10
    if transport != "stdio":
        assert captured["transport"]["sse_read_timeout"] == (None if tool_execution else 20)
        assert captured["transport"]["timeout"] == 30  # connection/write budget


def test_remote_inspection_waits_without_resubmitting_or_switching_early(tmp_path, monkeypatch):
    from src.remote_workspace import client, device_tools
    from src.remote_workspace.inspection import inspect_workspace
    inspection = inspect_workspace(str(tmp_path))
    monkeypatch.setattr(device_tools, "_worker_catalog", lambda: [{
        "worker_id": "worker", "online": True, "capabilities": ["inspect_workspace"]}])
    requests = []
    def post(path, body, timeout):
        requests.append(dict(body))
        if len(requests) == 1:
            return {"ok": True, "result": json.dumps({"status": "running", "remote_task_id": body["task_id"]})}
        return {"ok": True, "result": inspection.model_dump_json()}
    monkeypatch.setattr(client, "_post_internal_request", post)
    assert device_tools._inspect("worker", str(tmp_path)) == inspection
    assert len(requests) == 2 and requests[1]["action"] == "wait"
    assert requests[0]["task_id"] == requests[1]["task_id"]


def test_native_capture_reports_without_stopping_capture(monkeypatch):
    from src.computer_use import windows_capture as capture_module
    events = {}
    stopped = []
    reports = []
    class Control:
        def stop(self):
            stopped.append(True)
        def is_finished(self):
            return bool(stopped)
    class Capture:
        def __init__(self, **kwargs):
            pass
        def event(self, callback):
            events[callback.__name__] = callback
        def start_free_threaded(self):
            return Control()
    class Done:
        def wait(self, seconds):
            if reports:
                assert stopped == []
                events["on_closed"]()
                return True
            return False
        def set(self):
            pass
    monkeypatch.setitem(sys.modules, "windows_capture", SimpleNamespace(WindowsCapture=Capture))
    monkeypatch.setattr(capture_module, "threading", SimpleNamespace(Event=Done))
    monkeypatch.setattr(capture_module, "time", SimpleNamespace(monotonic=iter([0, 9]).__next__))
    monkeypatch.setattr(capture_module, "report_tool_progress", lambda progress, **kwargs: reports.append(progress))
    from src.computer_use.contracts import ComputerUseError
    with pytest.raises(ComputerUseError, match="Window closed"):
        capture_module.capture_window(123, None)
    assert reports[0]["state"] == "waiting_for_window_frame" and stopped == [True]


def test_uia_worker_preserves_task_context_for_progress_and_cancellation():
    from src.computer_use.windows_uia import _AutomationRuntime
    from src.tool.tool_tasks import current_tool_task, report_tool_progress
    from src.runtime_cancellation import current_tool_call_cancel_source
    runtime = _AutomationRuntime(lambda: SimpleNamespace(desktop=object()), lambda state: None)
    release = threading.Event()
    agent = SimpleNamespace(config={"toolExecutionTimeoutSec": 0})
    with tool_task_scope(agent):
        tools = BaseTool(agent)
        def native():
            def operation(desktop):
                assert current_tool_task() is not None and current_tool_call_cancel_source() is not None
                report_tool_progress({"state": "uia_busy"}, request_report=True)
                assert release.wait(3)
                return {"value": 42}
            return runtime.call(operation)
        tools.function_map["native"] = native
        try:
            first = decode(tools.execute_tool("native", {}))
            assert first["status"] == "running" and first["progress"]["state"] == "uia_busy"
        finally:
            release.set()
            runtime.close()
        assert decode(tools.execute_tool("wait_tool_task", {"task_id": first["task_id"], "wait_seconds": 1}))["value"] == 42
