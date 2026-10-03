import inspect
import json
from types import SimpleNamespace

import pytest

from functions.agent_schedule_tools import manage_agent_schedule, manage_agent_schedule_declaration
from src.access_policy import DEFAULT_NONDEVELOPER_FILTERED_TOOLS
from src.providers.agent_runtime_context import AgentRuntimeContext, bind_agent_runtime_context
from src.tool.base_tool import BaseTool


def bound_agent(callback):
    agent = SimpleNamespace(config={})
    bind_agent_runtime_context(agent, AgentRuntimeContext(
        graph_id="graph-a", node_id="agent-a", task_id="task-a", manage_schedule=callback,
    ))
    return agent


def test_system_tools_registers_agent_schedule_tool():
    tool = BaseTool(SimpleNamespace(config={}))
    tool.addTool("system_tools")
    assert tool.function_map["manage_agent_schedule"] is manage_agent_schedule
    assert manage_agent_schedule_declaration in tool.tool_declarations
    assert "agent_schedule_tools" in DEFAULT_NONDEVELOPER_FILTERED_TOOLS


def test_create_forwards_exact_arguments_to_bound_callback():
    calls = []

    def callback(action, **params):
        calls.append((action, params))
        return {"schedule": {"schedule_id": "wake-1", "revision": 1}}

    result = json.loads(manage_agent_schedule(
        "create", prompt="Check the build", delay_seconds=90, idempotency_key="build-followup",
        agent=bound_agent(callback),
    ))
    assert result == {"status": "success", "result": {"schedule": {"schedule_id": "wake-1", "revision": 1}}}
    assert calls == [("create", {
        "prompt": "Check the build", "delay_seconds": 90, "idempotency_key": "build-followup",
    })]


@pytest.mark.parametrize("params", [
    {"schedule_id": "wake-1", "expected_revision": 2, "prompt": "Check new build"},
    {"schedule_id": "wake-1", "expected_revision": 2, "interval_seconds": None},
    {"schedule_id": "wake-1", "expected_revision": 2, "run_at": "2026-10-03T18:00:00+08:00"},
])
def test_update_preserves_omitted_fields_and_explicit_null(params):
    calls = []

    def callback(action, **kwargs):
        calls.append((action, kwargs))
        return {}

    assert json.loads(manage_agent_schedule("update", agent=bound_agent(callback), **params))["status"] == "success"
    assert calls == [("update", params)]


@pytest.mark.parametrize("action,params", [
    ("list", {}),
    ("get", {"schedule_id": "wake-1"}),
    ("cancel", {"schedule_id": "wake-1", "expected_revision": 3}),
])
def test_read_and_cancel_operations_forward_only_supplied_fields(action, params):
    calls = []

    def callback(operation, **kwargs):
        calls.append((operation, kwargs))
        return {"ok": True}

    result = json.loads(manage_agent_schedule(action, agent=bound_agent(callback), **params))
    assert result == {"status": "success", "result": {"ok": True}}
    assert calls == [(action, params)]


def test_missing_bound_runtime_is_rejected():
    result = json.loads(manage_agent_schedule("list", agent=SimpleNamespace(config={})))
    assert result["status"] == "error"
    assert "bound backend runtime" in result["error"]


def test_owner_identity_is_not_model_supplied():
    schema = manage_agent_schedule_declaration["function"]["parameters"]
    assert schema["additionalProperties"] is False
    for field in ("graph_id", "node_id", "task_id", "agent_id", "workspace_root"):
        assert field not in schema["properties"]
        assert field not in inspect.signature(manage_agent_schedule).parameters
        with pytest.raises(TypeError):
            manage_agent_schedule("list", **{field: "other-owner"})
    assert "agent" not in schema["properties"]


def test_backend_error_is_reported_without_success():
    def callback(action, **params):
        raise ValueError("expected_revision conflict")

    result = json.loads(manage_agent_schedule("cancel", agent=bound_agent(callback)))
    assert result == {"status": "error", "error": "ValueError: expected_revision conflict"}


def test_backend_must_return_object():
    result = json.loads(manage_agent_schedule("list", agent=bound_agent(lambda action: None)))
    assert result["status"] == "error"
    assert "must return an object" in result["error"]
