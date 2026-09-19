from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.harness.memory_reset import CLI_HARNESSES, clear_harness_memory
from src.harness.session_state import resolve_state_directory
from src.web_backend.node_cancellation import NodeCancellationRegistry
from src.web_backend.node_memory_reset import NodeMemoryResetBlocked, NodeMemoryResetError, reset_node_memory


def seed(root: Path) -> Path:
    root.mkdir(parents=True)
    state = resolve_state_directory(root, previous_binding=["p", "m", "cwd", ""])
    for name in ("conversation.json", "home/state.db", "home/memories/MEMORY.md",
                 "home/memories/USER.md", "session.json", "session.jsonl", "agent/sessions/old.jsonl"):
        path = state / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("old private memory", encoding="utf-8")
    (root / "workspace").mkdir()
    (root / "workspace" / "user-work.txt").write_text("keep", encoding="utf-8")
    legacy = root / ("a" * 24)
    legacy.mkdir()
    (legacy / "history").write_text("old", encoding="utf-8")
    return state


@pytest.mark.parametrize("harness", CLI_HARNESSES)
def test_clear_memory_endpoint_clears_native_state_and_keeps_work(harness):
    import src.web_backend as backend
    from src.web_backend.runtime_paths import _get_graphs_dir

    client = TestClient(backend.create_app())
    node_id = "harness-clear-test"
    created = client.post("/api/nodes/instances", json={
        "node_id": node_id, "type_id": harness + "_node", "graph_id": "default",
        "ui": {"grid_x": 1, "grid_y": 2},
    })
    assert created.status_code == 200, created.text
    node = Path(_get_graphs_dir()) / "default" / node_id
    root = node / ".harness" / harness
    old_state = seed(root)
    sibling = node.parent / "other-node" / ".harness" / harness
    sibling_state = seed(sibling)
    config_before = json.loads((node / "config.json").read_text(encoding="utf-8"))

    result = client.post(f"/api/nodes/instances/{node_id}/clear-memory?graph_id=default")
    assert result.status_code == 200, result.text
    assert str(old_state) in result.json()["cleared_harness_paths"]
    assert not old_state.exists()
    assert not (root / ("a" * 24)).exists()
    assert not (root / "current-session.json").exists()
    repeated = client.post(f"/api/nodes/instances/{node_id}/clear-memory?graph_id=default")
    assert repeated.status_code == 200 and repeated.json()["cleared_harness_paths"] == []
    assert (root / "workspace" / "user-work.txt").read_text(encoding="utf-8") == "keep"
    assert (sibling_state / "conversation.json").exists()
    after = json.loads((node / "config.json").read_text(encoding="utf-8"))
    for key in ("provider_id", "model", "instruction", "working_path"):
        assert after.get(key) == config_before.get(key)
    new_state = resolve_state_directory(root, previous_binding=["p", "m", "cwd", ""])
    assert new_state != old_state
    assert list(new_state.iterdir()) == []


@pytest.mark.parametrize("node_type", ["codex", "claude"])
def test_persistent_runtime_is_closed_and_resume_selection_removed(tmp_path, monkeypatch, node_type):
    from importlib import import_module
    module = import_module(f"nodes.{node_type}_node.runtime.session_manager")
    manager_class = getattr(module, "CodexSessionManager" if node_type == "codex" else "ClaudeSessionManager")
    closed = []
    monkeypatch.setattr(manager_class, "instance", lambda: SimpleNamespace(close_session=closed.append))
    state = tmp_path / f"{node_type}_session.json"
    state.write_text("old selection", encoding="utf-8")
    assert clear_harness_memory(str(tmp_path), {"type_id": node_type + "_node",
        "node_id": "node", "graph_id": "graph"}) == (str(state),)
    assert len(closed) == 1 and os.path.normcase(str(state)) in closed[0]
    assert not state.exists()


def reset(tmp_path, registry):
    return reset_node_memory(core=SimpleNamespace(node_cancellations=registry, node_runs={}),
        config_path=str(tmp_path / "config.json"), memory_path=str(tmp_path / "memory.md"),
        messages_path=str(tmp_path / "messages.jsonl"), node_directory=str(tmp_path), wait_timeout_seconds=0)


def test_busy_node_keeps_native_memory(tmp_path):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    old = seed(tmp_path / ".harness" / "hermes_agent")
    registry = NodeCancellationRegistry()
    event = registry.begin(str(tmp_path / "config.json"))
    try:
        with pytest.raises(NodeMemoryResetBlocked):
            reset(tmp_path, registry)
        assert old.exists()
    finally:
        registry.end(str(tmp_path / "config.json"), event)


def test_deletion_error_is_not_reported_as_success(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    old = seed(tmp_path / ".harness" / "hermes_agent")
    def fail(path):
        raise PermissionError("database still open")
    monkeypatch.setattr("src.harness.memory_reset.shutil.rmtree", fail)
    with pytest.raises(NodeMemoryResetError, match="database still open"):
        reset(tmp_path, NodeCancellationRegistry())
    assert old.exists()


def test_linked_state_cannot_delete_another_directory(tmp_path):
    root = tmp_path / "node" / ".harness" / "hermes_agent"
    root.mkdir(parents=True)
    external = tmp_path / "other-node"
    external.mkdir()
    marker = external / "memory.txt"
    marker.write_text("keep other memory", encoding="utf-8")
    try:
        (root / ("b" * 32)).symlink_to(external, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks unavailable: {exc}")
    with pytest.raises(ValueError, match="not owned"):
        clear_harness_memory(str(tmp_path / "node"), {})
    assert marker.read_text(encoding="utf-8") == "keep other memory"
