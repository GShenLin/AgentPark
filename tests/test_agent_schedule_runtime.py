import threading
import time

import pytest

from src.message_protocol import envelope_text
from src.web_backend import state_store
from src.web_backend.core import BackendCore
from src.web_backend.runtime_state_memory_store import runtime_state_memory_store
from src.web_backend.scheduled_node_registry import ScheduledNodeRegistry, ScheduledNodeRegistration


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    runtime = BackendCore().graph_runtime
    path = tmp_path / "memories" / "studio" / "worker" / "config.json"
    path.parent.mkdir(parents=True)
    state_store._write_json_dict(str(path), {"node_id": "worker", "type_id": "agent_node", "state": "idle"})
    monkeypatch.setattr(runtime, "_ensure_graph_runner", lambda _: None)
    monkeypatch.setattr(runtime, "_wake_graph_runner", lambda _: None)
    return runtime, str(path)


def create_due(runtime, monkeypatch, **extra):
    monkeypatch.setattr("src.agent_schedule_store.time.time", lambda: 1000.0)
    context = {"graph_id": "studio", "node_instance_id": "worker", "node_type_id": "agent_node",
               "task_id": "original-task", "access_role": "nondeveloper", "access_client_id": "client-1"}
    record = runtime._manage_agent_schedule(context, "create", prompt="Continue checking the result", delay_seconds=5,
                                            idempotency_key="test", **extra)
    monkeypatch.setattr("src.agent_schedule_store.time.time", lambda: 1006.0)
    return record, context


def execute(runtime, path, item):
    runtime._run_node_with_agent_schedule(safe_graph_id="studio", entry="worker", config_path=path,
                                         pending_item=item, cfg={}, outgoing={}, nodes_dir="nodes", wake_event=threading.Event())


def test_poll_deduplicates_and_preserves_task_and_access(runtime, monkeypatch):
    runtime, path = runtime
    create_due(runtime, monkeypatch)
    assert runtime._poll_agent_schedules() == 1
    assert runtime._poll_agent_schedules() == 0
    item = state_store._dequeue_node_pending_to_working(path)
    assert item["source"] == "agent_schedule"
    assert item["_access_role"] == "nondeveloper"
    captured = []
    def run(**kwargs):
        captured.append(kwargs["pending_item"].copy())
        kwargs["pending_item"]["_agent_schedule_result"] = "completed"
    monkeypatch.setattr(runtime, "_run_single_node_iteration", run)
    execute(runtime, path, item)
    assert captured[0]["_agent_schedule_task_id"] == "original-task"
    assert captured[0]["trace_id"] != "original-task"
    assert envelope_text(captured[0]["payload"]) == "Continue checking the result"
    assert runtime._poll_agent_schedules() == 0
    assert runtime._agent_schedule_store().due() == []


def test_cancel_queued_occurrence_prevents_execution(runtime, monkeypatch):
    runtime, path = runtime
    record, context = create_due(runtime, monkeypatch)
    runtime._poll_agent_schedules()
    current = runtime._manage_agent_schedule(context, "get", schedule_id=record["schedule_id"])
    runtime._manage_agent_schedule(context, "cancel", schedule_id=record["schedule_id"], expected_revision=current["revision"])
    monkeypatch.setattr(runtime, "_run_single_node_iteration", lambda **_: pytest.fail("cancelled task ran"))
    execute(runtime, path, state_store._dequeue_node_pending_to_working(path))
    assert state_store._read_json_dict(path)["state"] == "idle"
    assert runtime._poll_agent_schedules() == 0


def test_restart_requeues_lost_queue_and_running_delivery(runtime, monkeypatch):
    runtime, path = runtime
    create_due(runtime, monkeypatch)
    runtime._poll_agent_schedules()
    item = state_store._dequeue_node_pending_to_working(path)
    store = runtime._agent_schedule_store()
    assert store.begin(item["_agent_schedule_occurrence"], "studio", "worker")
    runtime_state_memory_store.replace(path, {})  # Existing startup recovery clears this projection.
    restarted = BackendCore().graph_runtime
    monkeypatch.setattr(restarted, "_ensure_graph_runner", lambda _: None)
    monkeypatch.setattr(restarted, "_wake_graph_runner", lambda _: None)
    restarted._agent_schedule_store().reset_running()
    assert restarted._poll_agent_schedules() == 1
    replay = state_store._dequeue_node_pending_to_working(path)
    assert replay["trace_id"] == item["trace_id"]


def test_stopped_node_defers_delivery(runtime, monkeypatch):
    runtime, path = runtime
    create_due(runtime, monkeypatch)
    runtime_state_memory_store.update(path, lambda cfg: cfg.update(state="stop"))
    assert runtime._poll_agent_schedules() == 0
    assert runtime._agent_schedule_store().due()[0]["status"] == "pending"
    runtime_state_memory_store.update(path, lambda cfg: cfg.update(state="idle"))
    assert runtime._poll_agent_schedules() == 1


def test_running_periodic_delivery_does_not_overlap(runtime, monkeypatch):
    runtime, path = runtime
    create_due(runtime, monkeypatch, interval_seconds=60)
    runtime._poll_agent_schedules()
    item = state_store._dequeue_node_pending_to_working(path)
    runtime._agent_schedule_store().begin(item["_agent_schedule_occurrence"], "studio", "worker")
    monkeypatch.setattr("src.agent_schedule_store.time.time", lambda: 2000.0)
    assert runtime._poll_agent_schedules() == 0
    assert len(runtime._agent_schedule_store().due()) == 1


def test_execution_failure_is_terminal_not_an_infinite_retry(runtime, monkeypatch):
    runtime, path = runtime
    create_due(runtime, monkeypatch)
    runtime._poll_agent_schedules()
    def fail(**_):
        raise RuntimeError("model failed")
    monkeypatch.setattr(runtime, "_run_single_node_iteration", fail)
    with pytest.raises(RuntimeError, match="model failed"):
        execute(runtime, path, state_store._dequeue_node_pending_to_working(path))
    assert runtime._agent_schedule_store().due() == []


def test_bounded_registry_wait_allows_outbox_polling():
    registry = ScheduledNodeRegistry()
    registry.register(ScheduledNodeRegistration("g", "n", "config.json", "clock_node", time.time() + 3600))
    start = time.monotonic()
    assert registry.wait_for_due(threading.Event(), max_wait=0.02) == []
    assert time.monotonic() - start < 0.5


def test_real_execution_binds_schedule_callback_and_original_task(runtime, monkeypatch):
    runtime, path = runtime
    create_due(runtime, monkeypatch)
    runtime._poll_agent_schedules()
    captured = {}
    def node_logic(_nodes, _type, message, context):
        captured.update(context)
        assert envelope_text(message) == "Continue checking the result"
        created = context["manage_schedule"]("create", prompt="Next step", delay_seconds=100, idempotency_key="next")
        assert created["task_id"] == "original-task"
        return {"message": {"role": "assistant", "parts": [{"type": "text", "text": "done"}]}, "routes": []}
    monkeypatch.setattr("src.web_backend.graph_node_execution._run_node_logic_with_routes", node_logic)
    monkeypatch.setattr(runtime, "_emit_runtime_event", lambda **_: None)
    monkeypatch.setattr(runtime, "_evaluate_node_goal_after_persist", lambda **_: {"should_continue": False})
    item = state_store._dequeue_node_pending_to_working(path)
    execute(runtime, path, item)
    assert captured["task_id"] == "original-task"
    assert captured["node_instance_id"] == "worker"
    assert captured["access_role"] == "nondeveloper"
    assert captured["memory_path"].endswith("studio/worker/memory.md")
    assert item["_agent_schedule_result"] == "completed"
    assert runtime._agent_schedule_store().due() == []


def test_missing_target_becomes_terminal(runtime, monkeypatch):
    import os
    runtime, path = runtime
    create_due(runtime, monkeypatch)
    os.unlink(path)
    assert runtime._poll_agent_schedules() == 0
    assert runtime._agent_schedule_store().due() == []


def test_bad_delivery_does_not_starve_another_node(runtime, monkeypatch):
    runtime, path = runtime
    create_due(runtime, monkeypatch)
    other = path.replace("/worker/", "/other/")
    state_store._write_json_dict(other, {"node_id": "other", "type_id": "agent_node", "state": "idle"})
    runtime._manage_agent_schedule({"graph_id": "studio", "node_instance_id": "other", "node_type_id": "agent_node",
                                   "task_id": "other-task"}, "create", prompt="other work", delay_seconds=1, idempotency_key="other")
    monkeypatch.setattr("src.agent_schedule_store.time.time", lambda: 1010.0)
    original = state_store._append_node_pending
    def append(target, item):
        if target == path:
            raise state_store.NodeDeletingError("being deleted")
        return original(target, item)
    monkeypatch.setattr(state_store, "_append_node_pending", append)
    assert runtime._poll_agent_schedules() == 1
    assert len(state_store._read_json_dict(other)["pending"]) == 1
    assert all(delivery["node_id"] == "other" for delivery in runtime._agent_schedule_store().due())


def test_changed_node_type_between_queue_and_execution_cannot_run(runtime, monkeypatch):
    runtime, path = runtime
    create_due(runtime, monkeypatch)
    runtime._poll_agent_schedules()
    item = state_store._dequeue_node_pending_to_working(path)
    cfg = state_store._read_json_dict(path)
    cfg["type_id"] = "console_command_node"
    state_store._write_json_dict(path, cfg)
    monkeypatch.setattr(runtime, "_run_single_node_iteration", lambda **_: pytest.fail("wrong node type ran"))
    execute(runtime, path, item)
    assert runtime._agent_schedule_store().due() == []


def test_wrong_owner_cannot_terminalize_delivery_with_replaced_type(runtime, monkeypatch):
    runtime, path = runtime
    create_due(runtime, monkeypatch)
    runtime._poll_agent_schedules()
    item = state_store._dequeue_node_pending_to_working(path)
    other = path.replace("/worker/", "/other/")
    state_store._write_json_dict(other, {"node_id": "other", "type_id": "console_command_node"})
    runtime._run_node_with_agent_schedule(safe_graph_id="studio", entry="other", config_path=other,
                                         pending_item=item, cfg={}, outgoing={}, nodes_dir="nodes", wake_event=threading.Event())
    deliveries = runtime._agent_schedule_store().due()
    assert len(deliveries) == 1 and deliveries[0]["status"] == "pending"


def test_agent_node_exposes_bound_callback_and_restores_history(runtime, monkeypatch):
    import nodes.agent_node as node_module
    from functions.agent_schedule_tools import manage_agent_schedule
    from tests.agent_invocation_helpers import configured_fake
    import json

    runtime, path = runtime
    captured = {}
    class FakeAgent:
        def __init__(self):
            self.messages = []
            self.config = {"model": "test-model"}
        def addTool(self, _):
            pass
        def Message(self, role, content, **_):
            self.messages.append({"role": role, "content": content})
        def Send(self, **_):
            captured["agent"] = self
            captured["result"] = json.loads(manage_agent_schedule("create", prompt="Next", delay_seconds=5,
                                                                  idempotency_key="from-provider", agent=self))
            return "done"
    monkeypatch.setattr(node_module, "create_agent", lambda *_, **kw: configured_fake(FakeAgent(), kw.get("agent_config")))
    monkeypatch.setattr(node_module.ConfigLoader, "get_provider_config", lambda *_: {"supportmode": ["chat"]})
    monkeypatch.setattr(node_module, "_workspace_config", lambda: {})
    monkeypatch.setattr(node_module, "load_agent_history_messages", lambda **_: [{"role": "user", "content": "Earlier task details"}])
    context = {"task_id": "original-task", "graph_id": "studio", "node_instance_id": "worker",
               "node_type_id": "agent_node", "provider_id": "test-provider", "node_config_path": path,
               "memory_path": path.replace("config.json", "memory.md"),
               "messages_path": path.replace("config.json", "messages.jsonl")}
    context["manage_schedule"] = lambda action, **params: runtime._manage_agent_schedule(context, action, **params)
    node_module.Node().on_input("Resume task", context)
    assert captured["result"]["status"] == "success"
    assert captured["result"]["result"]["task_id"] == "original-task"
    assert {"role": "user", "content": "Earlier task details"} in captured["agent"].messages
