import json
import threading
from types import SimpleNamespace

import pytest

from src.providers.agent_runtime_context import (
    AgentRuntimeContext, bind_agent_runtime_context, get_agent_runtime_context,
)
from src.providers.tool_call_execution import execute_tool_call_envelopes_parallel
from src.remote_workspace import device_tools
from src.remote_workspace.device_state import device_state, execution_operation
from src.remote_workspace.inspection import inspect_workspace
from src.remote_workspace.model_context import refresh_execution_messages
from src.tool.base_tool import BaseTool
from src.tool.tool_call_protocol import ToolCallEnvelope


def make_agent(path):
    agent = SimpleNamespace(config={"working_path": str(path)}, messages=[])
    bind_agent_runtime_context(agent, AgentRuntimeContext(working_path=str(path)))
    agent.tools = BaseTool(agent)
    agent.tools.addTool("execution_device_tools")
    return agent


def switch(agent, path, revision=0, device="local"):
    return json.loads(agent.tools.execute_tool("switch_execution_device", {
        "device_id": device, "working_path": str(path), "expected_revision": revision,
    }))


def test_local_switch_updates_live_routing_without_persisting_config(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    agent = make_agent(a)
    agent.tools.addTool("file_write_tools")
    result = switch(agent, b)
    assert result["status"] == "success"
    assert result["current"]["revision"] == 1
    assert agent.config["working_path"] == str(a)
    agent.tools.execute_tool("write_file", {"file_path": "code.py", "content": "answer = 42\n"})
    assert (b / "code.py").read_text() == "answer = 42\n"
    assert not (a / "code.py").exists()
    assert switch(agent, a, 1)["current"]["revision"] == 2


def test_failed_inspection_and_stale_revision_preserve_target(tmp_path):
    agent = make_agent(tmp_path)
    original = get_agent_runtime_context(agent)
    assert switch(agent, tmp_path / "missing")["status"] == "exception"
    assert switch(agent, tmp_path, True)["status"] == "exception"
    assert switch(agent, tmp_path, 7)["status"] == "exception"
    assert get_agent_runtime_context(agent) == original
    assert device_state(agent).revision == 0


def test_running_operation_and_session_block_switch(tmp_path):
    agent = make_agent(tmp_path)
    with execution_operation(agent, "read_file"):
        assert "still running" in switch(agent, tmp_path)["error"]
    session = SimpleNamespace(done=threading.Event())
    agent._console_session_registry = SimpleNamespace(lock=threading.RLock(), sessions={"s": session})
    assert "console session" in switch(agent, tmp_path)["error"]
    session.done.set()
    assert switch(agent, tmp_path)["status"] == "success"


def test_detached_timed_out_tool_keeps_device_ownership(tmp_path):
    agent = make_agent(tmp_path)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def slow_tool(agent=None):
        entered.set()
        try:
            release.wait(5)
            return "done"
        finally:
            finished.set()
    slow_tool.tool_timeout_seconds = .05
    agent.tools.function_map["slow_tool"] = slow_tool
    try:
        result = agent.tools.execute_tool_result("slow_tool", {})
        assert result.status == "timeout" and entered.is_set()
        assert "still running" in switch(agent, tmp_path)["error"]
    finally:
        release.set()
        assert finished.wait(3)


def test_switch_reservation_blocks_other_tools_and_cancel_does_not_commit(tmp_path, monkeypatch):
    agent = make_agent(tmp_path)
    entered, release = threading.Event(), threading.Event()
    agent.cancel_event = threading.Event()
    original = device_tools._inspect
    def inspect(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)
    monkeypatch.setattr(device_tools, "_inspect", inspect)
    results = []
    thread = threading.Thread(target=lambda: results.append(switch(agent, tmp_path)))
    thread.start()
    assert entered.wait(3)
    try:
        with pytest.raises(RuntimeError, match="in progress"):
            with execution_operation(agent, "write_file"):
                pytest.fail("write entered during switch")
        agent.cancel_event.set()
    finally:
        release.set(); thread.join(3)
    assert results[0]["status"] == "stopped"
    assert device_state(agent).revision == 0


def test_mixed_batch_has_no_side_effects():
    calls = [ToolCallEnvelope(name, str(i), {}, "{}", "test") for i, name in enumerate(
        ["write_file", "switch_execution_device"])]
    def unexpected(*args, **kwargs):
        pytest.fail("mixed device-switch batch executed")
    results = execute_tool_call_envelopes_parallel(
        tool_calls=calls, execute_tool_call=unexpected, execute_tasks_parallel_ordered=unexpected,
    )
    assert len(results) == 2 and all(result.status == "error" for result in results)


def test_remote_inspection_rejects_offline_unsupported_and_malformed_targets(tmp_path, monkeypatch):
    agent = make_agent(tmp_path)
    worker = {"worker_id": "worker-b", "online": False, "capabilities": []}
    monkeypatch.setattr(device_tools, "_worker_catalog", lambda: [worker])
    assert "offline" in switch(agent, "/workspace", device="worker-b")["error"]
    worker["online"] = True
    assert "update" in switch(agent, "/workspace", device="worker-b")["error"]
    worker["capabilities"] = ["inspect_workspace"]
    monkeypatch.setattr(device_tools, "_post_internal_request", lambda *args: {"ok": True, "result": '{}'})
    assert switch(agent, "/workspace", device="worker-b")["status"] == "exception"
    assert device_state(agent).revision == 0


@pytest.mark.parametrize("responses", [False, True])
def test_next_model_request_replaces_stale_device_and_project_context(tmp_path, monkeypatch, responses):
    agent = make_agent(tmp_path)
    inspection = inspect_workspace(str(tmp_path)).model_copy(update={
        "working_path": "/work/code", "platform": "linux", "shell": "bash", "timezone": "UTC",
        "project_instructions": inspect_workspace(str(tmp_path)).project_instructions.model_copy(
            update={"directory": "/work/code", "paths": ["/work/code/AGENTS.md"], "text": "Use pytest on B."}),
    })
    monkeypatch.setattr(device_tools, "_inspect", lambda *args: inspection)
    assert switch(agent, "/work/code", device="B")["status"] == "success"
    old = [
        {"role": "user", "content": "<environment_context>old shell</environment_context>"},
        {"role": "user", "content": "# AGENTS.md instructions\n<INSTRUCTIONS>Old project</INSTRUCTIONS>"},
        {"role": "user", "content": "Read A and implement on B"},
    ]
    result = refresh_execution_messages(agent, old, responses=responses)
    result = refresh_execution_messages(agent, result, responses=responses)
    text = json.dumps(result)
    assert "old shell" not in text and "Old project" not in text
    assert "bash" in text and "Use pytest on B." in text
    assert "Read A and implement on B" in text
    assert text.count("<execution_workspace_update>") == 1


def test_skill_loads_tools_through_normal_activation(tmp_path):
    from pathlib import Path
    from nodes.agent_skill_loader import load_node_skills
    from nodes.agent_skill_runtime import SkillRuntime
    skill = load_node_skills(["cross-device-workflow"], skill_root=str(
        Path(__file__).resolve().parents[1] / ".agents" / "skills"))[0]
    agent = make_agent(tmp_path)
    agent.tools = BaseTool(agent)
    runtime = SkillRuntime(agent, {skill.name: skill}, {}, "system")
    result = runtime.change(skill.name, active=True)
    assert set(result["tools_added"]) == {
        "list_execution_devices", "inspect_execution_workspace", "switch_execution_device",
    }
    assert switch(agent, tmp_path)["status"] == "success"
