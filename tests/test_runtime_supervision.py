import asyncio
import json
import socket
import threading

import src.runtime_supervision as supervision_module
from src.runtime_supervision import RuntimeSupervisor


def _events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_listener_probe_records_only_state_transitions(monkeypatch, tmp_path):
    monkeypatch.setattr(supervision_module, "get_workspace_root", lambda: str(tmp_path))
    supervisor = RuntimeSupervisor()
    supervisor.configure_listener("127.0.0.1", 8788)
    outcomes = iter([OSError("listener gone"), None, None])

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_connection(*_args, **_kwargs):
        outcome = next(outcomes)
        if outcome is not None:
            raise outcome
        return Connection()

    monkeypatch.setattr(socket, "create_connection", fake_connection)
    supervisor._probe_listener()
    supervisor._probe_listener()
    supervisor._probe_listener()

    transitions = [event for event in _events(tmp_path / ".runtime" / "server-lifecycle.jsonl") if event["event"] == "listener_state_changed"]
    assert [event["healthy"] for event in transitions] == [False, True]
    assert transitions[0]["level"] == "error"
    assert transitions[0]["threads"]


def test_dead_critical_thread_is_reported_once(monkeypatch, tmp_path):
    monkeypatch.setattr(supervision_module, "get_workspace_root", lambda: str(tmp_path))
    supervisor = RuntimeSupervisor()
    thread = threading.Thread(target=lambda: None, name="critical-test")
    thread.start()
    thread.join(timeout=1.0)
    supervisor.register_critical_thread("critical-test", thread)

    supervisor._probe_critical_threads()
    supervisor._probe_critical_threads()

    events = _events(tmp_path / ".runtime" / "server-lifecycle.jsonl")
    failures = [event for event in events if event["event"] == "critical_thread_dead"]
    assert len(failures) == 1
    assert failures[0]["critical_thread"] == "critical-test"


def test_asyncio_exception_handler_records_and_delegates(monkeypatch, tmp_path):
    monkeypatch.setattr(supervision_module, "get_workspace_root", lambda: str(tmp_path))
    supervisor = RuntimeSupervisor()
    loop = asyncio.new_event_loop()
    delegated = []
    loop.set_exception_handler(lambda _loop, context: delegated.append(context))
    try:
        supervisor.attach_asyncio_loop(loop)
        context = {"message": "accept failed", "exception": OSError(64, "network name unavailable")}
        loop.call_exception_handler(context)
    finally:
        loop.close()

    events = _events(tmp_path / ".runtime" / "server-lifecycle.jsonl")
    failure = next(event for event in events if event["event"] == "asyncio_unhandled_exception")
    assert failure["exception_type"] == "OSError"
    assert "network name unavailable" in failure["exception"]
    assert delegated == [context]
