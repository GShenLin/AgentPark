import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src import desktop_runtime
from src.web_backend import node_memory_store, node_conversation_activity as activity
from src.web_backend.desktop_tray_api import DesktopTrayApi
from src.web_backend.desktop_tray_snapshot import build_tray_snapshot
from src.web_backend.node_config_service import node_config_service
from src.web_backend.runtime_state_memory_store import runtime_state_memory_store


def node(root, graph, name, state="idle"):
    directory = root / graph / name
    directory.mkdir(parents=True)
    node_config_service.write(str(directory / "config.json"), {
        "node_id": name, "name": name, "type_id": "agent_node", "state": state,
    })
    return directory


def save(directory, text="hello"):
    node_memory_store.append_node_memory_entry(
        str(directory / "memory.md"), str(directory / "messages.jsonl"), "assistant", text,
    )


def test_recent_uses_successful_commits_deduplicates_and_limits(tmp_path, monkeypatch):
    clock = iter(range(1, 30))
    monkeypatch.setattr(activity.time, "time_ns", lambda: next(clock))
    directories = [node(tmp_path, "g", f"node-{i}") for i in range(12)]
    for directory in directories:
        save(directory)
    save(directories[0])
    # Opening/updating configuration cannot bump recency.
    node_config_service.patch_persistent_fields(str(directories[1] / "config.json"), {"name": "edited"})
    result = build_tray_snapshot(tmp_path)
    assert len(result.recent) == 10
    assert [item.node_id for item in result.recent[:3]] == ["node-0", "node-11", "node-10"]
    assert len({(item.graph_id, item.node_id) for item in result.recent}) == 10
    # A fresh read uses durable metadata, independent of runtime state.
    runtime_state_memory_store.clear(str(directories[0] / "config.json"))
    assert build_tray_snapshot(tmp_path).recent[0].node_id == "node-0"


def test_working_is_live_and_distinguishes_same_named_nodes(tmp_path):
    first = node(tmp_path, "a", "Agent", "working")
    second = node(tmp_path, "b", "Agent", "working")
    node(tmp_path, "b", "stopped", "stop")
    save(first)
    result = build_tray_snapshot(tmp_path)
    assert [(n.graph_id, n.node_id) for n in result.working] == [("a", "Agent"), ("b", "Agent")]
    assert result.recent[0].node_id == "Agent"
    runtime_state_memory_store.replace(str(second / "config.json"), {"state": "idle"})
    assert len(build_tray_snapshot(tmp_path).working) == 1


def test_rename_move_and_deletion_follow_node_storage(tmp_path):
    directory = node(tmp_path, "g", "old")
    save(directory)
    new = tmp_path / "h" / "renamed"
    new.parent.mkdir()
    directory.rename(new)
    node_config_service.patch_persistent_fields(str(new / "config.json"), {"node_id": "new", "name": "New name"})
    item = build_tray_snapshot(tmp_path).recent[0]
    assert (item.graph_id, item.node_id, item.name) == ("h", "new", "New name")
    (new / "config.json").unlink()
    assert build_tray_snapshot(tmp_path).recent == []


def test_failed_history_writes_do_not_update_recent(tmp_path, monkeypatch):
    directory = node(tmp_path, "g", "Agent")
    assert activity.read_conversation_commit(directory) is None
    save(directory)
    before = activity.read_conversation_commit(directory)
    monkeypatch.setattr(node_memory_store, "_append_jsonl_record", Mock(side_effect=OSError("disk full")))
    with pytest.raises(node_memory_store.NodeMemoryPersistenceError):
        save(directory)
    assert activity.read_conversation_commit(directory) == before


def test_invalid_commit_metadata_is_visible(tmp_path):
    directory = node(tmp_path, "g", "Agent")
    (directory / activity.FILENAME).write_text('{"saved_at_ns": "yesterday"}', encoding="utf-8")
    with pytest.raises(ValueError):
        build_tray_snapshot(tmp_path)


@pytest.fixture
def tray_api(tmp_path, monkeypatch):
    monkeypatch.setattr("src.web_backend.runtime_paths._get_graphs_dir", lambda: str(tmp_path))
    core = SimpleNamespace(
        node_windows=SimpleNamespace(open_local=Mock(return_value={"ok": True})),
        restart_recovery=SimpleNamespace(capture_running_nodes=Mock()),
        system_api=SimpleNamespace(restart_server=Mock(return_value={"ok": True}), request_workspace_exit=Mock(return_value={"ok": True})),
    )
    api = DesktopTrayApi(core)
    app = FastAPI()
    app.websocket("/api/desktop/tray")(api.connect)
    return app, api, core


def connect(app, host="127.0.0.1", origin="http://127.0.0.1:8788"):
    return TestClient(app, client=(host, 1234)).websocket_connect(
        "ws://127.0.0.1:8788/api/desktop/tray", headers={"origin": origin},
    )


def authenticate(socket, api):
    socket.send_json({"token": api.token})
    assert socket.receive_json() == {"ready": True}


def test_authenticated_commands_and_dynamic_snapshot(tray_api, tmp_path):
    app, api, core = tray_api
    with connect(app) as socket:
        authenticate(socket, api)
        socket.send_json({"id": "1", "action": "snapshot"})
        assert socket.receive_json()["result"] == {"recent": [], "working": []}
        directory = node(tmp_path, "g", "中文 Agent", "working")
        save(directory)
        socket.send_json({"id": "2", "action": "snapshot"})
        assert socket.receive_json()["result"]["working"][0]["node_id"] == "中文 Agent"
        socket.send_json({"id": "3", "action": "open-node", "graph_id": "g", "node_id": "中文 Agent"})
        assert socket.receive_json()["ok"]
        core.node_windows.open_local.assert_called_once_with("中文 Agent", "g", 8788)
        socket.send_json({"id": "4", "action": "restart"})
        assert socket.receive_json()["ok"]
        core.restart_recovery.capture_running_nodes.assert_called_once()
        core.system_api.restart_server.assert_called_once()
        socket.send_json({"id": "5", "action": "exit"})
        assert socket.receive_json()["ok"]
        core.system_api.request_workspace_exit.assert_called_once()


def test_failure_is_reported_and_checkpoint_failure_blocks_restart(tray_api):
    app, api, core = tray_api
    core.restart_recovery.capture_running_nodes.side_effect = RuntimeError("checkpoint failed")
    with connect(app) as socket:
        authenticate(socket, api)
        socket.send_json({"id": "1", "action": "restart"})
        assert socket.receive_json() == {"id": "1", "ok": False, "error": "checkpoint failed"}
        core.system_api.restart_server.assert_not_called()
        socket.send_json({"id": "2", "action": "snapshot"})
        assert socket.receive_json()["ok"]


@pytest.mark.parametrize("host,origin", [
    ("192.168.1.2", "http://127.0.0.1:8788"),
    ("127.0.0.1", "https://evil.example"),
    ("127.0.0.1", "http://127.0.0.1:9999"),
])
def test_remote_and_cross_origin_connections_rejected(tray_api, host, origin):
    with pytest.raises(WebSocketDisconnect):
        with connect(tray_api[0], host, origin):
            pytest.fail("untrusted connection accepted")


def test_invalid_capability_and_extra_command_fields_rejected(tray_api):
    app, api, _ = tray_api
    with connect(app) as socket:
        socket.send_json({"token": "wrong"})
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    with connect(app) as socket:
        authenticate(socket, api)
        socket.send_json({"id": "1", "action": "exit", "arbitrary": True})
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()


@pytest.mark.skipif(os.name != "nt", reason="Windows desktop host")
def test_host_launch_is_hidden_and_removes_electron_node_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_runtime, "get_workspace_root", lambda: str(tmp_path))
    executable = tmp_path / "desktop/node-window/node_modules/electron/dist/electron.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    launch = Mock()
    monkeypatch.setattr(desktop_runtime.subprocess, "Popen", launch)
    monkeypatch.setenv("ELECTRON_RUN_AS_NODE", "1")
    desktop_runtime.launch_desktop_tray(9898, "a" * 64)
    args, kwargs = launch.call_args
    assert "--origin=http://127.0.0.1:9898" in args[0]
    assert "--tray" in args[0]
    assert "ELECTRON_RUN_AS_NODE" not in kwargs["env"]
    assert kwargs["creationflags"] & desktop_runtime.subprocess.CREATE_NO_WINDOW


def test_desktop_launch_waits_for_uvicorn_startup(monkeypatch):
    events = []
    async def startup(server, sockets=None):
        events.append("listener")
        server.started = True
    monkeypatch.setattr(desktop_runtime.uvicorn.Server, "startup", startup)
    monkeypatch.setattr(desktop_runtime, "launch_desktop_tray", lambda *args: events.append(args))
    config = desktop_runtime.uvicorn.Config(SimpleNamespace(state=SimpleNamespace(desktop_tray=SimpleNamespace(token="cap"))), port=9898)
    coroutine = desktop_runtime.DesktopServer(config).startup()
    with pytest.raises(StopIteration):
        coroutine.send(None)
    assert events == (["listener", (9898, "cap")] if os.name == "nt" else ["listener"])
