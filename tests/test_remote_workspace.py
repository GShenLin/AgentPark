import threading
import time
from types import SimpleNamespace

import pytest

from src.remote_workspace.broker import PROTOCOL_VERSION, RemoteWorkspaceBroker
from src.remote_workspace.routing import REMOTE_WORKSPACE_TOOL_NAMES, remote_workspace_target


def _register(broker: RemoteWorkspaceBroker, *, source_ip: str = "10.0.0.8", worker_id: str = "worker-1"):
    credentials = broker.register(
        {
            "protocol_version": PROTOCOL_VERSION,
            "worker_id": worker_id,
            "token": "secret-token",
            "display_name": "Alice-PC",
            "host_kind": "standalone",
            "workspace_path": r"D:\Projects\Game",
            "capabilities": sorted(REMOTE_WORKSPACE_TOOL_NAMES | {"select_folder"}),
        },
        source_ip,
    )
    return credentials


def test_pairing_selects_the_only_worker_from_the_browser_ip():
    broker = RemoteWorkspaceBroker()
    _register(broker)

    paired = broker.pair_for_ip("10.0.0.8")

    assert paired["worker_id"] == "worker-1"
    assert paired["host_kind"] == "standalone"
    assert paired["workspace_path"] == r"D:\Projects\Game"


def test_pairing_rejects_zero_or_multiple_workers_from_the_browser_ip():
    broker = RemoteWorkspaceBroker()

    with pytest.raises(LookupError, match="No online AgentPark remote worker"):
        broker.pair_for_ip("10.0.0.8")

    _register(broker, worker_id="worker-1")
    _register(broker, worker_id="worker-2")
    with pytest.raises(RuntimeError, match="Multiple remote workers"):
        broker.pair_for_ip("10.0.0.8")


def test_remote_target_requires_absolute_worker_path():
    relative_agent = SimpleNamespace(
        config={
            "remote_enabled": True,
            "remote_worker_id": "worker-1",
            "working_path": "Source",
        }
    )
    with pytest.raises(ValueError, match="must be an absolute path"):
        remote_workspace_target(relative_agent, "read_file")

    windows_agent = SimpleNamespace(
        config={
            "remote_enabled": True,
            "remote_worker_id": "worker-1",
            "working_path": r"D:\Projects\Game",
        }
    )
    target = remote_workspace_target(windows_agent, "read_file")
    assert target is not None
    assert target.working_path == r"D:\Projects\Game"


def test_remote_target_only_routes_workspace_tools():
    agent = SimpleNamespace(
        config={
            "remote_enabled": True,
            "remote_worker_id": "worker-1",
            "working_path": r"D:\Projects\Game",
        }
    )

    assert remote_workspace_target(agent, "read_file") is not None
    assert remote_workspace_target(agent, "cancer_control") is not None
    assert remote_workspace_target(agent, "ue_remote_control") is not None
    assert remote_workspace_target(agent, "web_search") is None


def test_broker_round_trip_preserves_worker_result():
    broker = RemoteWorkspaceBroker()
    credentials = _register(broker)
    received = {}

    def worker():
        task = broker.poll(credentials["worker_id"], credentials["token"], 2)
        assert task is not None
        received.update(task)
        broker.submit_result(
            credentials["worker_id"],
            credentials["token"],
            task["task_id"],
            {"ok": True, "result": '{"status":"success","content":"remote"}'},
        )

    thread = threading.Thread(target=worker)
    thread.start()
    result = broker.execute(
        {
            "worker_id": credentials["worker_id"],
            "tool_name": "read_file",
            "working_path": r"D:\Projects\Game",
            "arguments": {"file_path": "README.md"},
            "timeout_seconds": 2,
        }
    )
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert received["working_path"] == r"D:\Projects\Game"
    assert received["arguments"] == {"file_path": "README.md"}
    assert result == '{"status":"success","content":"remote"}'


def test_wait_for_worker_online_returns_the_bound_worker_without_repairing():
    broker = RemoteWorkspaceBroker()
    _register(broker, worker_id="bound-worker")

    worker = broker.wait_for_worker_online("bound-worker", timeout_seconds=0)

    assert worker["worker_id"] == "bound-worker"


def test_wait_for_worker_online_accepts_same_worker_reconnect():
    broker = RemoteWorkspaceBroker()
    _register(broker, worker_id="bound-worker")
    broker._workers["bound-worker"].last_seen = time.monotonic() - 60
    reconnected = threading.Event()

    def reconnect():
        time.sleep(0.03)
        _register(broker, worker_id="bound-worker")
        reconnected.set()

    thread = threading.Thread(target=reconnect)
    thread.start()
    worker = broker.wait_for_worker_online("bound-worker", timeout_seconds=0.5)
    thread.join(timeout=1)

    assert reconnected.is_set()
    assert worker["worker_id"] == "bound-worker"


def test_wait_for_worker_online_does_not_switch_to_another_worker():
    broker = RemoteWorkspaceBroker()
    _register(broker, worker_id="other-worker")

    with pytest.raises(LookupError, match="bound-worker"):
        broker.wait_for_worker_online("bound-worker", timeout_seconds=0.01)


def test_execute_waits_once_for_bound_worker_reconnect():
    broker = RemoteWorkspaceBroker()
    completed = threading.Event()

    def reconnect_and_execute():
        time.sleep(0.03)
        credentials = _register(broker, worker_id="bound-worker")
        task = broker.poll(credentials["worker_id"], credentials["token"], 1)
        assert task is not None
        broker.submit_result(
            credentials["worker_id"],
            credentials["token"],
            task["task_id"],
            {"ok": True, "result": "reconnected"},
        )
        completed.set()

    thread = threading.Thread(target=reconnect_and_execute)
    thread.start()
    result = broker.execute(
        {
            "worker_id": "bound-worker",
            "tool_name": "read_file",
            "working_path": r"D:\Projects\Game",
            "arguments": {"file_path": "README.md"},
            "timeout_seconds": 1,
        }
    )
    thread.join(timeout=1)

    assert completed.is_set()
    assert result == "reconnected"


def test_base_node_remote_companion_fields_are_hidden_but_have_defaults():
    from nodes.base_node import BaseNode

    node = BaseNode()
    defaults = node.get_config_defaults()
    schema = node.get_config_schema()

    assert defaults["remote_enabled"] is False
    assert defaults["remote_worker_id"] == ""
    assert schema["remote_enabled"]["hidden"] is True
    assert schema["remote_worker_id"]["hidden"] is True
