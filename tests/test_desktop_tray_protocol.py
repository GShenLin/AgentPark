"""Exercise the actual ASGI WebSocket protocol without an OS network/event loop."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, WebSocket

from src.web_backend import desktop_tray_api as module


@pytest.fixture
def protocol(tmp_path, monkeypatch):
    monkeypatch.setattr(module.runtime_paths, "_get_graphs_dir", lambda: str(tmp_path))
    core = SimpleNamespace(
        node_windows=SimpleNamespace(open_local=Mock(return_value={"ok": True})),
        restart_recovery=SimpleNamespace(capture_running_nodes=Mock()),
        system_api=SimpleNamespace(restart_server=Mock(return_value={"ok": True}), request_workspace_exit=Mock(return_value={"ok": True})),
    )
    api = module.DesktopTrayApi(core)

    async def in_thread(function, *args):
        return function(*args)

    async def wait_for(awaitable, timeout):
        return await awaitable

    monkeypatch.setattr(module.asyncio, "to_thread", in_thread)
    monkeypatch.setattr(module.asyncio, "wait_for", wait_for)

    def run(commands, *, host="127.0.0.1", origin="http://127.0.0.1:8788", token=None):
        frames = iter([
            {"type": "websocket.connect"},
            {"type": "websocket.receive", "text": json.dumps({"token": api.token if token is None else token})},
            *[{"type": "websocket.receive", "text": json.dumps(command)} for command in commands],
            {"type": "websocket.disconnect", "code": 1000},
        ])
        output = []
        async def receive():
            return next(frames)
        async def send(message):
            output.append(message)
        websocket = WebSocket({
            "type": "websocket", "app": FastAPI(), "scheme": "ws", "path": "/api/desktop/tray",
            "client": (host, 1234), "server": ("127.0.0.1", 8788), "headers": [(b"origin", origin.encode())],
        }, receive, send)
        coroutine = api.connect(websocket)
        try:
            with pytest.raises(StopIteration):
                coroutine.send(None)
        finally:
            coroutine.close()
        return [json.loads(frame["text"]) if frame["type"] == "websocket.send" else frame for frame in output]
    return run, core


def test_protocol_snapshot_open_restart_exit(protocol):
    run, core = protocol
    output = run([
        {"id": "1", "action": "snapshot"},
        {"id": "2", "action": "open-node", "graph_id": "g", "node_id": "中文 Agent"},
        {"id": "3", "action": "restart"},
        {"id": "4", "action": "exit"},
    ])
    assert output[1] == {"ready": True}
    assert output[2] == {"id": "1", "ok": True, "result": {"recent": [], "working": []}}
    assert all(item["ok"] for item in output[2:])
    core.node_windows.open_local.assert_called_once_with("中文 Agent", "g", 8788)
    core.restart_recovery.capture_running_nodes.assert_called_once()
    core.system_api.restart_server.assert_called_once()
    core.system_api.request_workspace_exit.assert_called_once()
    assert core.system_api.request_workspace_exit.call_args.kwargs["reason"] == "exit requested by tray"


@pytest.mark.parametrize("kwargs", [
    {"host": "192.168.1.1"}, {"origin": "https://evil.example"},
    {"origin": "http://127.0.0.1:9999"}, {"token": "invalid"},
])
def test_protocol_access_controls(protocol, kwargs):
    run, core = protocol
    output = run([{"id": "1", "action": "exit"}], **kwargs)
    assert output[-1]["type"] == "websocket.close"
    assert output[-1]["code"] == 1008
    core.system_api.request_workspace_exit.assert_not_called()


@pytest.mark.parametrize("command", [
    {"id": "1", "action": "open-node", "graph_id": "g"},
    {"id": "1", "action": "exit", "unknown": True},
    {"id": 1, "action": "snapshot"},
    {"id": "1", "action": "execute-shell"},
])
def test_protocol_rejects_invalid_commands(protocol, command):
    output = protocol[0]([command])
    assert output[-1]["type"] == "websocket.close"
    assert output[-1]["code"] == 1008


def test_protocol_checkpoint_failure_prevents_restart_and_keeps_channel_usable(protocol):
    run, core = protocol
    core.restart_recovery.capture_running_nodes.side_effect = RuntimeError("checkpoint failed")
    output = run([{"id": "1", "action": "restart"}, {"id": "2", "action": "snapshot"}])
    assert output[2] == {"id": "1", "ok": False, "error": "checkpoint failed"}
    assert output[3]["ok"]
    core.system_api.restart_server.assert_not_called()
