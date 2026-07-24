import threading
import time

from src.tool.base_tool import BaseTool
from src.runtime_cancellation import CancellationRequested
from src.runtime_cancellation import cancel_source_from_agent
from src.runtime_cancellation import raise_if_cancel_requested
from src.tool.tool_call_protocol import ToolCallEnvelope
from src.web_backend.node_cancellation import NodeCancellationRegistry
from src.web_backend.tool_call_cancellation import ToolCallCancellationRegistry
from src.web_backend.state_store import _cancel_node_work, _consume_node_mid_turn_user_inputs, _read_json_dict, _write_json_dict


def test_node_cancellation_registry_requests_active_event(tmp_path):
    config_path = str(tmp_path / "config.json")
    registry = NodeCancellationRegistry()

    event = registry.begin(config_path)
    try:
        assert registry.request(config_path) == 1
        assert event.is_set()
    finally:
        registry.end(config_path, event)

    assert registry.request(config_path) == 0


def test_tool_call_cancellation_registry_targets_only_requested_call(tmp_path):
    config_path = str(tmp_path / "config.json")
    registry = ToolCallCancellationRegistry()

    first = registry.begin(config_path, "call-1")
    second = registry.begin(config_path, "call-2")
    try:
        assert registry.request(config_path, "call-1") is True
        assert first.is_set()
        assert not second.is_set()
        assert registry.request(config_path, "missing") is False
    finally:
        registry.end(config_path, "call-1", first)
        registry.end(config_path, "call-2", second)

    assert not registry.is_active(config_path, "call-1")
    assert not registry.is_active(config_path, "call-2")


def test_cancel_node_work_marks_inflight_for_active_cancel(tmp_path):
    config_path = str(tmp_path / "config.json")
    _write_json_dict(
        config_path,
        {
            "state": "working",
            "pending": [{"payload": "queued"}],
            "pending_count": 1,
            "inflight": {"payload": "running"},
        },
    )

    result = _cancel_node_work(config_path)

    assert result["cleared_pending"] == 1
    assert result["cleared_inflight"] is True
    assert result["state"] == "working"


def test_consume_mid_turn_user_inputs_removes_only_direct_user_emit_pending(tmp_path):
    config_path = str(tmp_path / "config.json")
    eligible = {
        "source": "emit",
        "from": "agent1",
        "depth": 0,
        "payload": {"role": "user", "parts": [{"type": "text", "text": "new constraint"}]},
    }
    routed = {
        "source": "propagate",
        "from": "upstream",
        "depth": 1,
        "payload": {"role": "assistant", "parts": [{"type": "text", "text": "routed"}]},
    }
    _write_json_dict(
        config_path,
        {
            "node_id": "agent1",
            "state": "working",
            "inflight": {"payload": "running"},
            "pending": [eligible, routed],
            "pending_count": 2,
        },
    )

    consumed = _consume_node_mid_turn_user_inputs(config_path)

    assert consumed == [eligible]
    cfg = _read_json_dict(config_path)
    assert cfg["pending"] == [routed]
    assert cfg["pending_count"] == 1


def test_base_tool_returns_stopped_when_cancelled_before_timeout():
    class Agent:
        def __init__(self):
            self.config = {}
            self.cancel_event = threading.Event()

    agent = Agent()
    tool = BaseTool(agent)

    def slow_tool(agent=None):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if agent.cancel_event.is_set():
                raise CancellationRequested("cancelled by test")
            time.sleep(0.02)
        return "done"

    tool.function_map["slow"] = slow_tool
    agent.cancel_event.set()

    started = time.monotonic()
    result = tool.execute_tool_result("slow", {})

    assert result.status == "stopped"
    assert time.monotonic() - started < 0.5


def test_base_tool_call_stop_returns_exact_model_result_and_unregisters_call():
    class Agent:
        def __init__(self):
            self.config = {}
            self.events = []
            self.tool_event_callback = self.events.append
            self.call_events = {}

        def begin_call(self, call_id):
            event = threading.Event()
            self.call_events[call_id] = event
            return event

        def end_call(self, call_id, event):
            if self.call_events.get(call_id) is event:
                self.call_events.pop(call_id, None)

    agent = Agent()
    agent._agentpark_begin_tool_call_cancellation = agent.begin_call
    agent._agentpark_end_tool_call_cancellation = agent.end_call
    tool = BaseTool(agent)

    def waiting_tool(agent=None):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            raise_if_cancel_requested(cancel_source_from_agent(agent))
            time.sleep(0.02)
        return "too late"

    tool.function_map["waiting_tool"] = waiting_tool
    call = ToolCallEnvelope(
        name="waiting_tool",
        call_id="call-stop",
        arguments={},
        arguments_json="{}",
        provider="unit",
    )
    result_holder = []
    worker = threading.Thread(target=lambda: result_holder.append(tool.execute_tool_call(call)))
    worker.start()

    deadline = time.monotonic() + 1
    while "call-stop" not in agent.call_events and time.monotonic() < deadline:
        time.sleep(0.01)
    assert "call-stop" in agent.call_events
    agent.call_events["call-stop"].set()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert len(result_holder) == 1
    execution = result_holder[0]
    assert execution.status == "stopped"
    assert execution.cleaned_result == "UserStoppedThisCall"
    assert "call-stop" not in agent.call_events
    assert [event["type"] for event in agent.events] == ["tool_call_start", "tool_call_end"]
    assert agent.events[-1]["status"] == "stopped"
    assert agent.events[-1]["result_preview"] == "UserStoppedThisCall"


def test_uncooperative_tool_does_not_claim_user_stop_succeeded():
    class Agent:
        def __init__(self):
            self.config = {}
            self.call_event = threading.Event()

    agent = Agent()
    agent._agentpark_begin_tool_call_cancellation = lambda _call_id: agent.call_event
    tool = BaseTool(agent)

    def uncooperative_tool():
        time.sleep(1.5)
        return "late"

    tool.function_map["uncooperative_tool"] = uncooperative_tool
    call = ToolCallEnvelope(
        name="uncooperative_tool",
        call_id="call-uncooperative",
        arguments={},
        arguments_json="{}",
        provider="unit",
    )
    result_holder = []
    worker = threading.Thread(target=lambda: result_holder.append(tool.execute_tool_call(call)))
    worker.start()
    time.sleep(0.05)
    agent.call_event.set()
    worker.join(timeout=1.2)

    assert not worker.is_alive()
    assert result_holder[0].status == "cancellation_failed"
    assert result_holder[0].cleaned_result != "UserStoppedThisCall"
