import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest

from src.tool.base_tool import BaseTool
from src.tool.tool_tasks import task_registry_for, tool_task_scope
from src.runtime_cancellation import cancel_source_from_agent, raise_if_cancel_requested
from tests.test_console_sessions import command


def payload(result):
    value = result.model_output()
    return json.loads(value) if isinstance(value, str) else value


@pytest.fixture
def owner(tmp_path):
    agent = SimpleNamespace(config={"working_path": str(tmp_path), "toolExecutionTimeoutSec": 0.1},
                            cancel_event=threading.Event())
    with tool_task_scope(agent):
        yield agent


def test_generic_tool_is_resumed_once_and_wait_duration_is_model_selected(owner):
    tools = BaseTool(owner)
    release = threading.Event()
    calls = []
    def slow():
        calls.append(1)
        release.wait(5)
        return {"status": "success", "value": 42}
    tools.function_map["slow"] = slow
    try:
        first = tools.execute_tool_result("slow", {})
        assert first.status == "running"
        task_id = payload(first)["task_id"]
        second = payload(tools.execute_tool_result("wait_tool_task", {"task_id": task_id, "wait_seconds": 0.15}))
        assert second["status"] == "running" and second["wait_seconds"] == 0.15
        assert second["next_report_at"] and calls == [1]
    finally:
        release.set()
    final = payload(tools.execute_tool_result("wait_tool_task", {"task_id": task_id, "wait_seconds": 2}))
    assert final["value"] == 42 and calls == [1]


def test_cooperative_tool_is_not_cancelled_by_reporting_but_explicit_stop_works(owner):
    tools = BaseTool(owner)
    def slow(agent=None):
        source = cancel_source_from_agent(agent)
        while True:
            raise_if_cancel_requested(source)
            time.sleep(0.01)
    slow.tool_cooperative_cancellation = True
    tools.function_map["slow"] = slow
    first = payload(tools.execute_tool_result("slow", {}))
    assert not first["cancel_requested"]
    final = tools.execute_tool_result("stop_tool_task", {"task_id": first["task_id"]})
    assert final.status == "stopped"


def test_command_survives_its_internal_interval_and_returns_final_output(owner, tmp_path):
    tools = BaseTool(owner)
    tools.addTool("system_tools")
    owner.config["toolExecutionTimeoutSec"] = 0
    first = payload(tools.execute_tool_result("execute_console_command", {
        "command": command("import time,pathlib; print('started',flush=True); time.sleep(2); pathlib.Path('finished').write_text('ok'); print('done')"),
        "timeout_seconds": 1,
    }))
    assert first["status"] == "running"
    assert first["progress"]["pid"]
    final = payload(tools.execute_tool_result("wait_tool_task", {"task_id": first["task_id"], "wait_seconds": 10}))
    assert final["status"] == "success" and "done" in final["stdout"]
    assert (tmp_path / "finished").read_text() == "ok"


def test_workspace_dependencies_do_not_advance_at_reporting_boundary(owner, tmp_path):
    tools = BaseTool(owner)
    tools.addTool("system_tools")
    from src.tool.workspace_exec_tools import workspace_exec
    tools.function_map["workspace_exec"] = workspace_exec
    first = payload(tools.execute_tool_result("workspace_exec", {"stages": [
        {"id": "download", "operations": [{"id": "a", "kind": "run_command", "arguments": {
            "command": command("import time,pathlib; time.sleep(1); pathlib.Path('ready').write_text('ok')"), "timeout_seconds": 1}}]},
        {"id": "build", "operations": [{"id": "b", "kind": "run_command", "arguments": {
            "command": command("import pathlib; assert pathlib.Path('ready').exists(); pathlib.Path('built').write_text('ok')")}}]},
    ]}))
    assert first["status"] == "running" and not (tmp_path / "built").exists()
    final = payload(tools.execute_tool_result("wait_tool_task", {"task_id": first["task_id"], "wait_seconds": 10}))
    assert final["status"] == "success" and (tmp_path / "built").exists()


def test_unknown_task_and_invalid_wait_are_rejected(owner):
    tools = BaseTool(owner)
    assert tools.execute_tool_result("wait_tool_task", {"task_id": "unknown", "wait_seconds": 0}).status == "exception"
    assert tools.execute_tool_result("wait_tool_task", {"task_id": "unknown", "wait_seconds": float("nan")}).status == "exception"


def test_original_tool_card_receives_final_status_after_reporting(owner):
    from src.tool.tool_call_protocol import ToolCallEnvelope
    events = []
    release = threading.Event()
    finished = threading.Event()
    def event_callback(event):
        events.append(event)
        if event.get("type") == "tool_call_end" and event.get("status") == "completed":
            finished.set()
    owner.tool_event_callback = event_callback
    tools = BaseTool(owner)
    tools.function_map["slow"] = lambda: release.wait(5)
    try:
        result = tools.execute_tool_call(ToolCallEnvelope(call_id="original", name="slow", arguments={}, arguments_json="{}", provider="test"))
        assert result.status == "running"
    finally:
        release.set()
    assert finished.wait(2)
    ends = [event["status"] for event in events if event["type"] == "tool_call_end"]
    assert ends == ["running", "completed"]


def test_remote_executor_reports_then_waits_without_reexecuting():
    from src.remote_workspace.execution import WorkspaceExecutor
    from src.peer_network.remote_contracts import RemoteRequest
    calls = []
    release = threading.Event()
    class Operations:
        def execute(self, task, cancel_event):
            calls.append(task.task_id)
            release.wait(5)
            assert not cancel_event.is_set()
            return '{"status":"success"}'
    async def scenario():
        executor = WorkspaceExecutor(Operations())
        request = RemoteRequest(action="execute", worker_id="w", task_id="task", tool_name="slow", working_path="C:/", timeout_seconds=0.05)
        try:
            first = await executor.dispatch("peer", request)
            assert json.loads(first["result"])["status"] == "running"
        finally:
            release.set()
        final = await executor.dispatch("peer", request.model_copy(update={"action": "wait", "timeout_seconds": 2.0}))
        assert json.loads(final["result"])["status"] == "success"
        assert calls == ["task"]
    asyncio.run(scenario())
