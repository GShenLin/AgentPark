"""A worker owns its node through persistence/routing, not only model execution."""

import threading

import pytest

from src.web_backend import state_store
from src.web_backend.graph_runner_runtime import _GraphRunnerWakeSignal
from src.web_backend.graph_runner_state import GraphExecutor, GraphRunnerState


@pytest.mark.parametrize("finishing_state", ["working", "idle"])
def test_notification_burst_cannot_overlap_finishing_node(monkeypatch, tmp_path, finishing_state):
    import src.web_backend as backend

    runtime = backend.WebBackendFacade().core.graph_runtime
    graph_dir = tmp_path / "studio"
    paths = {}
    for node_id, traces in [("producer", ["first", "notice-1", "notice-2"]), ("peer", ["peer-work"])]:
        node_dir = graph_dir / node_id
        node_dir.mkdir(parents=True)
        paths[node_id] = str(node_dir / "config.json")
        state_store._write_json_dict(paths[node_id], {
            "node_id": node_id, "type_id": "echo_node", "state": "idle",
            "input_num": 1, "output_num": 1,
            "pending": [{"payload": trace, "trace_id": trace} for trace in traces],
            "pending_count": len(traces),
        })

    finishing = threading.Event()
    release = threading.Event()
    peer_finished = threading.Event()
    calls = []

    def run(**kwargs):
        trace = kwargs["pending_item"]["trace_id"]
        calls.append(trace)
        path = kwargs["config_path"]
        cfg = state_store._read_json_dict(path)
        cfg.pop("inflight", None)
        cfg.pop("inflight_at", None)
        cfg["state"] = finishing_state if trace == "first" else "idle"
        state_store._write_json_dict(path, cfg)
        if trace == "first":
            finishing.set()
            assert release.wait(5), "test did not release the finishing worker"
            cfg = state_store._read_json_dict(path)
            cfg["state"] = "idle"
            state_store._write_json_dict(path, cfg)
        elif trace == "peer-work":
            peer_finished.set()

    monkeypatch.setattr(runtime, "_graph_dir", lambda _: str(graph_dir))
    monkeypatch.setattr(runtime, "_read_graph_config", lambda _: {"nodes": [], "output_routes": {}})
    monkeypatch.setattr(runtime, "_build_outgoing_routes_map", lambda _: {})
    monkeypatch.setattr(runtime, "_run_single_node_iteration", run)
    state = GraphRunnerState(None, threading.Event(), _GraphRunnerWakeSignal(), GraphExecutor("studio"))
    try:
        runtime._run_scheduler_batch("studio", state)
        assert finishing.wait(2)
        assert peer_finished.wait(2), "other group members must remain concurrent"
        for _ in range(5):
            runtime._run_scheduler_batch("studio", state)
        assert sorted(calls) == ["first", "peer-work"]
        cfg = state_store._read_json_dict(paths["producer"])
        assert cfg["state"] == finishing_state
        assert [item["trace_id"] for item in cfg["pending"]] == ["notice-1", "notice-2"]
        release.set()
        for task in list(state.active_tasks.values()):
            task.future.result(timeout=2)
        for trace in ["notice-1", "notice-2"]:
            runtime._run_scheduler_batch("studio", state)
            for task in list(state.active_tasks.values()):
                task.future.result(timeout=2)
            assert calls[-1] == trace
        assert calls.count("first") == 1
        assert not state_store._read_json_dict(paths["producer"])["pending"]
    finally:
        release.set()
        for task in list(state.active_tasks.values()):
            task.thread.join(timeout=2)
