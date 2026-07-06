import threading
import time

from src.tool.base_tool import BaseTool
from src.runtime_cancellation import CancellationRequested
from src.web_backend.node_cancellation import NodeCancellationRegistry
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
