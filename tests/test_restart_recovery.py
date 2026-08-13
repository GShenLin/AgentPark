from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.restart_recovery_context import render_restart_recovery_context
from src.web_backend.restart_recovery import RestartRecoveryCoordinator, RestartRecoveryError
from src.web_backend.runtime_state_memory_store import runtime_state_memory_store


class _Cancellations:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def request(self, config_path: str) -> None:
        self.requested.append(config_path)


class _GraphRuntime:
    def __init__(self) -> None:
        self.ensured: list[str] = []
        self.woken: list[str] = []
        self.events: list[tuple[str, str, dict]] = []

    @staticmethod
    def _sanitize_graph_id(graph_id: str) -> str:
        return graph_id

    def _ensure_graph_runner(self, graph_id: str) -> None:
        self.ensured.append(graph_id)

    def _wake_graph_runner(self, graph_id: str) -> None:
        self.woken.append(graph_id)

    def _log_graph_event(self, graph_id: str, event: str, **payload) -> None:
        self.events.append((graph_id, event, payload))


class _Core:
    def __init__(self, owner_id: str) -> None:
        self.runtime_owner_id = owner_id
        self.node_cancellations = _Cancellations()
        self.graph_runtime = _GraphRuntime()


def _write_node(graphs_dir: Path, graph_id: str, node_id: str, type_id: str = "agent_node") -> str:
    config_path = graphs_dir / graph_id / node_id / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "graph_id": graph_id,
                "node_id": node_id,
                "type_id": type_id,
                "name": node_id,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return str(config_path)


def test_restart_checkpoint_recovers_original_inflight_and_cleans_files(tmp_path):
    graphs_dir = tmp_path / "memories"
    cache_dir = tmp_path / ".cache"
    config_path = _write_node(graphs_dir, "default", "GPT13")
    original_inflight = {
        "payload": {"role": "user", "parts": [{"type": "text", "text": "继续原任务"}]},
        "trace_id": "trace-restart",
        "source": "mobile",
        "depth": 0,
        "_runtime_owner_id": "old-owner",
    }
    queued_item = {
        "payload": {"role": "user", "parts": [{"type": "text", "text": "后续任务"}]},
        "trace_id": "trace-next",
        "_runtime_owner_id": "old-owner",
    }
    runtime_state_memory_store.replace(
        config_path,
        {
            "state": "working",
            "inflight": original_inflight,
            "inflight_at": "2026-08-04T00:00:00+08:00",
            "pending": [queued_item],
            "goal": "finish recovery",
            "node_event_seq": 7,
        },
    )

    old_core = _Core("old-owner")
    coordinator = RestartRecoveryCoordinator(
        old_core,
        cache_dir=str(cache_dir),
        graphs_dir=str(graphs_dir),
    )
    captured = coordinator.capture_running_nodes()

    tag_path = cache_dir / "restart" / "default_GPT13.json"
    assert captured["captured"] == 1
    assert tag_path.is_file()
    tag = json.loads(tag_path.read_text(encoding="utf-8"))
    state_path = cache_dir / "restart" / tag["state_path"]
    assert state_path.is_file()
    assert old_core.node_cancellations.requested == []

    runtime_state_memory_store.replace(
        config_path,
        {
            "state": "idle",
            "pending": [
                {
                    "payload": {"role": "user", "parts": [{"type": "text", "text": "启动时新任务"}]},
                    "trace_id": "trace-arrived-during-startup",
                    "_runtime_owner_id": "new-owner",
                }
            ],
            "node_event_seq": 20,
        },
    )
    new_core = _Core("new-owner")
    recovered_by = RestartRecoveryCoordinator(
        new_core,
        cache_dir=str(cache_dir),
        graphs_dir=str(graphs_dir),
    )
    recovered = recovered_by.recover_pending_nodes()
    restored = runtime_state_memory_store.snapshot(config_path)

    assert recovered == {
        "ok": True,
        "recovered": 1,
        "claimed": 0,
        "completed_cleaned": 0,
        "failures": [],
    }
    assert restored["state"] == "idle"
    assert restored["goal"] == "finish recovery"
    assert restored["node_event_seq"] == 21
    assert [item["trace_id"] for item in restored["pending"]] == [
        "trace-restart",
        "trace-next",
        "trace-arrived-during-startup",
    ]
    assert all(item["_runtime_owner_id"] == "new-owner" for item in restored["pending"])
    recovery_reference = restored["pending"][0]["_restart_recovery"]
    assert recovery_reference["restart_id"] == captured["restart_id"]
    assert "继续原任务" not in render_restart_recovery_context(recovery_reference)
    assert "trace-restart" in render_restart_recovery_context(recovery_reference)
    assert new_core.graph_runtime.ensured == ["default"]
    assert new_core.graph_runtime.woken == ["default"]

    cleanup = recovered_by.complete_node_recovery(recovery_reference)

    assert cleanup["removed"] is True
    assert not tag_path.exists()
    assert not state_path.exists()
    runtime_state_memory_store.clear(config_path)


def test_checkpoint_validation_is_all_or_nothing(tmp_path):
    graphs_dir = tmp_path / "memories"
    cache_dir = tmp_path / ".cache"
    valid_path = _write_node(graphs_dir, "default", "valid")
    unsafe_path = _write_node(graphs_dir, "default", "unsafe")
    runtime_state_memory_store.replace(
        valid_path,
        {"state": "working", "inflight": {"payload": {"role": "user"}, "trace_id": "valid"}},
    )
    runtime_state_memory_store.replace(unsafe_path, {"state": "working"})
    coordinator = RestartRecoveryCoordinator(
        _Core("owner"),
        cache_dir=str(cache_dir),
        graphs_dir=str(graphs_dir),
    )

    with pytest.raises(RestartRecoveryError, match="unsafe"):
        coordinator.capture_running_nodes()

    restart_dir = cache_dir / "restart"
    assert not list(restart_dir.glob("*.json"))
    assert not list((restart_dir / "state").glob("*.json"))
    runtime_state_memory_store.clear(valid_path)
    runtime_state_memory_store.clear(unsafe_path)


def test_startup_finishes_interrupted_checkpoint_cleanup(tmp_path):
    graphs_dir = tmp_path / "memories"
    cache_dir = tmp_path / ".cache"
    config_path = _write_node(graphs_dir, "default", "GPT13")
    runtime_state_memory_store.replace(
        config_path,
        {"state": "working", "inflight": {"payload": {"role": "user"}, "trace_id": "trace"}},
    )
    coordinator = RestartRecoveryCoordinator(
        _Core("old-owner"),
        cache_dir=str(cache_dir),
        graphs_dir=str(graphs_dir),
    )
    coordinator.capture_running_nodes()
    tag_path = cache_dir / "restart" / "default_GPT13.json"
    tag = json.loads(tag_path.read_text(encoding="utf-8"))
    state_path = cache_dir / "restart" / tag["state_path"]
    tag["status"] = "completed"
    tag_path.write_text(json.dumps(tag, ensure_ascii=False), encoding="utf-8")
    runtime_state_memory_store.clear(config_path)

    result = RestartRecoveryCoordinator(
        _Core("new-owner"),
        cache_dir=str(cache_dir),
        graphs_dir=str(graphs_dir),
    ).recover_pending_nodes()

    assert result["completed_cleaned"] == 1
    assert result["recovered"] == 0
    assert not tag_path.exists()
    assert not state_path.exists()
