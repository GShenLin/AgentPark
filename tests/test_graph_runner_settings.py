import json
import threading
import time

from src.web_backend import state_store
from src.web_backend.graph_runner_runtime import _GraphRunnerWakeSignal
from src.web_backend.graph_runner_state import GraphExecutor, GraphRunnerState


def test_graph_runner_uses_one_scheduler():
    import src.web_backend as backend

    facade = backend.WebBackendFacade()
    graph_runtime = facade.core.graph_runtime
    graph_runtime._ensure_graph_runner("default")

    try:
        with facade.core.graph_runners_lock:
            state = facade.core.graph_runners.get("default")
        assert isinstance(state, GraphRunnerState)
        assert state.scheduler_thread is not None
        assert state.scheduler_thread.name == "graph-scheduler-default"
        assert state.scheduler_thread.is_alive()
        thread_names = [thread.name for thread in threading.enumerate()]
        assert "graph-scheduler-default" in thread_names
        assert not any(name.startswith("graph-runner-default") for name in thread_names)
        status = graph_runtime._runner_status("default")
        assert status["scheduler_running"] is True
        assert status["active_tasks"] == []
        assert status["ready_pending_count"] == 0
        assert status["running_node_count"] == 0
        assert "workers" not in status
        assert "worker_count" not in status
    finally:
        with facade.core.graph_runners_lock:
            state = facade.core.graph_runners.pop("default", None)
        if isinstance(state, GraphRunnerState):
            state.stop.set()
            state.wake.set()
            if state.scheduler_thread is not None:
                state.scheduler_thread.join(timeout=1.0)


def test_graph_scheduler_submits_one_task_per_ready_pending_node(monkeypatch, tmp_path):
    import src.web_backend as backend

    facade = backend.WebBackendFacade()
    graph_runtime = facade.core.graph_runtime
    graph_id = "default"
    graph_dir = tmp_path / graph_id
    graph_dir.mkdir()
    node_ids = [f"n{index}" for index in range(10)]
    for node_id in node_ids:
        node_dir = graph_dir / node_id
        node_dir.mkdir()
        state_store._write_json_dict(
            str(node_dir / "config.json"),
            {
                "node_id": node_id,
                "type_id": "echo_node",
                "state": "idle",
                "input_num": 1,
                "output_num": 1,
                "pending": [{"payload": "go", "trace_id": f"trace-{node_id}"}],
                "pending_count": 1,
            },
        )

    started = threading.Event()
    release = threading.Event()
    calls = []
    calls_lock = threading.Lock()

    def fake_run_single_node_iteration(**kwargs):
        with calls_lock:
            calls.append(kwargs["entry"])
            if len(calls) == len(node_ids):
                started.set()
        release.wait(timeout=2)

    monkeypatch.setattr(graph_runtime, "_graph_dir", lambda _graph_id: str(graph_dir))
    monkeypatch.setattr(graph_runtime, "_read_graph_config", lambda _graph_id: {"nodes": [], "output_routes": {}})
    monkeypatch.setattr(graph_runtime, "_build_outgoing_routes_map", lambda _graph_cfg: {})
    monkeypatch.setattr(graph_runtime, "_run_single_node_iteration", fake_run_single_node_iteration)

    state = GraphRunnerState(
        scheduler_thread=None,
        stop=threading.Event(),
        wake=_GraphRunnerWakeSignal(),
        executor=GraphExecutor(graph_id),
    )
    try:
        graph_runtime._run_scheduler_batch(graph_id, state)
        assert started.wait(timeout=1.0)
        with state.active_lock:
            assert set(state.active_tasks) == {f"trace-{node_id}:{node_id}" for node_id in node_ids}
            assert state.ready_pending_count == 0
    finally:
        release.set()
        for task in list(state.active_tasks.values()):
            task.thread.join(timeout=1.0)


def test_graph_scheduler_releases_finished_task_and_schedules_next_pending(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import state_store

    facade = backend.WebBackendFacade()
    graph_runtime = facade.core.graph_runtime
    graph_id = "default"
    graph_dir = tmp_path / graph_id
    graph_dir.mkdir()
    node_dir = graph_dir / "n1"
    node_dir.mkdir()
    config_path = node_dir / "config.json"
    state_store._write_json_dict(
        str(config_path),
        {
            "node_id": "n1",
            "type_id": "echo_node",
            "state": "idle",
            "input_num": 1,
            "output_num": 1,
            "pending": [
                {"payload": "first", "trace_id": "trace-1"},
                {"payload": "second", "trace_id": "trace-2"},
            ],
            "pending_count": 2,
        },
    )

    calls = []
    calls_lock = threading.Lock()

    def fake_run_single_node_iteration(**kwargs):
        with calls_lock:
            calls.append(kwargs["pending_item"]["trace_id"])
        cfg = state_store._read_json_dict(kwargs["config_path"])
        cfg["state"] = "idle"
        cfg.pop("inflight", None)
        cfg.pop("inflight_at", None)
        state_store._write_json_dict(kwargs["config_path"], cfg)

    monkeypatch.setattr(graph_runtime, "_graph_dir", lambda _graph_id: str(graph_dir))
    monkeypatch.setattr(graph_runtime, "_read_graph_config", lambda _graph_id: {"nodes": [], "output_routes": {}})
    monkeypatch.setattr(graph_runtime, "_build_outgoing_routes_map", lambda _graph_cfg: {})
    monkeypatch.setattr(graph_runtime, "_run_single_node_iteration", fake_run_single_node_iteration)

    state = GraphRunnerState(
        scheduler_thread=None,
        stop=threading.Event(),
        wake=_GraphRunnerWakeSignal(),
        executor=GraphExecutor(graph_id),
    )

    graph_runtime._run_scheduler_batch(graph_id, state)
    for task in list(state.active_tasks.values()):
        task.thread.join(timeout=1.0)

    graph_runtime._run_scheduler_batch(graph_id, state)
    for task in list(state.active_tasks.values()):
        task.thread.join(timeout=1.0)

    assert calls == ["trace-1", "trace-2"]


def test_graph_scheduler_skips_stop_and_delete_requested_nodes(monkeypatch, tmp_path):
    import src.web_backend as backend

    facade = backend.WebBackendFacade()
    graph_runtime = facade.core.graph_runtime
    graph_id = "default"
    graph_dir = tmp_path / graph_id
    graph_dir.mkdir()
    specs = {
        "stopped": {"state": "stop"},
        "deleting": {"state": "idle", "_delete_requested": True},
    }
    for node_id, extra in specs.items():
        node_dir = graph_dir / node_id
        node_dir.mkdir()
        payload = {
            "node_id": node_id,
            "type_id": "echo_node",
            "input_num": 1,
            "output_num": 1,
            "pending": [{"payload": "go", "trace_id": f"trace-{node_id}"}],
            "pending_count": 1,
            **extra,
        }
        state_store._write_json_dict(str(node_dir / "config.json"), payload)

    calls = []
    monkeypatch.setattr(graph_runtime, "_graph_dir", lambda _graph_id: str(graph_dir))
    monkeypatch.setattr(graph_runtime, "_read_graph_config", lambda _graph_id: {"nodes": [], "output_routes": {}})
    monkeypatch.setattr(graph_runtime, "_build_outgoing_routes_map", lambda _graph_cfg: {})
    monkeypatch.setattr(graph_runtime, "_run_single_node_iteration", lambda **kwargs: calls.append(kwargs["entry"]))

    state = GraphRunnerState(
        scheduler_thread=None,
        stop=threading.Event(),
        wake=_GraphRunnerWakeSignal(),
        executor=GraphExecutor(graph_id),
    )
    graph_runtime._run_scheduler_batch(graph_id, state)

    assert calls == []
    assert state.active_tasks == {}


def test_graph_scheduler_does_not_scan_before_explicit_wake(monkeypatch):
    import src.web_backend as backend

    facade = backend.WebBackendFacade()
    graph_runtime = facade.core.graph_runtime
    calls = []
    batch_ran = threading.Event()

    def fake_run_scheduler_batch(graph_id, state):
        calls.append(graph_id)
        batch_ran.set()

    monkeypatch.setattr(graph_runtime, "_run_scheduler_batch", fake_run_scheduler_batch)
    state = GraphRunnerState(
        scheduler_thread=None,
        stop=threading.Event(),
        wake=_GraphRunnerWakeSignal(),
        executor=GraphExecutor("default"),
    )
    thread = threading.Thread(
        target=graph_runtime._graph_scheduler_loop,
        args=("default", state),
        daemon=True,
    )
    state.scheduler_thread = thread
    thread.start()
    try:
        time.sleep(0.05)
        assert calls == []
        state.wake.set()
        assert batch_ran.wait(timeout=1.0)
        assert calls == ["default"]
    finally:
        state.stop.set()
        state.wake.set()
        thread.join(timeout=1.0)


def test_graph_runner_wake_signal_broadcasts_only_on_explicit_wake():
    signal = _GraphRunnerWakeSignal()
    stop_event = threading.Event()
    observed: list[int] = []
    lock = threading.Lock()

    def wait_once() -> None:
        generation = signal.wait(0, stop_event)
        with lock:
            observed.append(generation)

    threads = [threading.Thread(target=wait_once) for _ in range(3)]
    for thread in threads:
        thread.start()

    time.sleep(0.05)
    assert observed == []

    signal.set()
    for thread in threads:
        thread.join(timeout=1.0)

    assert not any(thread.is_alive() for thread in threads)
    assert observed == [1, 1, 1]
