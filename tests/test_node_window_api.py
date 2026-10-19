import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.web_backend import node_window_api
from src.web_backend.graph_event_stream import GraphEventStreamStore


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(node_window_api, "get_workspace_root", lambda: str(tmp_path))
    executable = tmp_path / "desktop/node-window/node_modules/electron/dist/electron.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    core = SimpleNamespace(graph_events=GraphEventStreamStore(), node_ops=SimpleNamespace(
        _resolve_node_instance_folder=lambda node, graph: (graph, node, "directory", "config")))
    api = node_window_api.NodeWindowApi(core)
    app = FastAPI()
    app.post('/api/nodes/instances/{node_id}/open-window')(api.open)
    app.websocket('/api/desktop/node-windows/focus')(api.focus)
    app.get('/api/desktop/node-windows/status')(api.status)
    app.state.node_windows = api
    calls = []

    def launch(argv, **kwargs):
        calls.append((argv, kwargs))
        receipt = next(arg.removeprefix('--receipt=') for arg in argv if arg.startswith('--receipt='))
        (tmp_path / '.runtime/node-windows' / f'{receipt}.json').write_text('{"ok": true}', encoding='utf-8')

    monkeypatch.setattr(node_window_api.subprocess, 'Popen', launch)
    return app, calls, executable, core


def client(app, host='127.0.0.1'):
    return TestClient(app, base_url='http://127.0.0.1:8788', client=(host, 12345))


def test_launch_uses_bound_listener_not_host_header_and_waits_for_readiness(setup, monkeypatch):
    app, calls, _, _ = setup
    monkeypatch.setenv('ELECTRON_RUN_AS_NODE', '1')
    response = client(app).post('/api/nodes/instances/Agent%20A/open-window?graph_id=图', headers={'host': 'attacker.example:9999'})
    assert response.status_code == 200
    argv, kwargs = calls[0]
    assert '--origin=http://127.0.0.1:8788' in argv
    assert '--graph=图' in argv and '--node=Agent A' in argv
    assert 'ELECTRON_RUN_AS_NODE' not in kwargs['env']
    assert not kwargs.get('shell')


@pytest.mark.parametrize('headers,host', [
    ({}, '192.168.1.10'),
    ({'origin': 'https://evil.example'}, '127.0.0.1'),
    ({'origin': 'http://127.0.0.1:1111'}, '127.0.0.1'),
    ({'sec-fetch-site': 'cross-site'}, '127.0.0.1'),
])
def test_remote_and_cross_site_cannot_launch_desktop(setup, headers, host):
    app, calls, _, _ = setup
    response = client(app, host).post('/api/nodes/instances/Agent/open-window?graph_id=default', headers=headers)
    assert response.status_code == 403
    assert not calls


def test_missing_host_is_actionable_not_a_fake_success(setup):
    app, calls, executable, _ = setup
    executable.unlink()
    response = client(app).post('/api/nodes/instances/Agent/open-window')
    assert response.status_code == 503
    assert 'npm ci' in response.json()['detail']
    assert not calls


def test_renderer_failure_is_propagated(setup, monkeypatch):
    app, _, executable, _ = setup
    root = executable.parents[5]

    def launch(argv, **_kwargs):
        receipt = next(arg.removeprefix('--receipt=') for arg in argv if arg.startswith('--receipt='))
        (root / '.runtime/node-windows' / f'{receipt}.json').write_text(json.dumps({'ok': False, 'error': 'Node not found'}))

    monkeypatch.setattr(node_window_api.subprocess, 'Popen', launch)
    response = client(app).post('/api/nodes/instances/Agent/open-window')
    assert response.status_code == 502
    assert response.json()['detail'] == 'Node not found'


def test_missing_node_never_launches(setup):
    app, calls, _, core = setup

    def missing(*_args):
        raise HTTPException(404, 'node instance not found')

    core.node_ops._resolve_node_instance_folder = missing
    assert client(app).post('/api/nodes/instances/missing/open-window').status_code == 404
    assert not calls


def test_browser_disconnect_releases_focus_and_backend_launches_without_a_browser(setup):
    from tests.test_node_window_alerts import wait_for
    app, calls, _, core = setup
    alerts = app.state.node_windows.alerts
    alerts.start(8788)
    try:
        with client(app).websocket_connect('ws://127.0.0.1:8788/api/desktop/node-windows/focus', headers={'origin': 'http://127.0.0.1:8788'}) as socket:
            socket.send_json({'focused': True})
            assert socket.receive_json() == {'focused': True}
            assert alerts.status()['focused_pages'] == 1
            core.graph_events.publish('default', {
                'event': 'work_persisted_alert', 'alert_id': 'visible', 'node_instance_id': 'Agent',
            })
            assert not calls
        assert alerts.status()['focused_pages'] == 0
        core.graph_events.publish('default', {
            'event': 'work_persisted_alert', 'alert_id': 'closed', 'node_instance_id': 'Agent',
        })
        wait_for(lambda: alerts.status()['last_delivery']['outcome'] == 'opened')
        assert len(calls) == 1
    finally:
        alerts.close()


@pytest.mark.parametrize('origin,host', [
    ('http://evil.example', '127.0.0.1'), ('http://127.0.0.1:8788', '10.0.0.2'),
    ('http://127.0.0.1:9999', '127.0.0.1'),
])
def test_remote_pages_cannot_suppress_local_notifications(setup, origin, host):
    from starlette.websockets import WebSocketDisconnect
    app, _, _, _ = setup
    with pytest.raises(WebSocketDisconnect):
        with client(app, host).websocket_connect('ws://127.0.0.1:8788/api/desktop/node-windows/focus', headers={'origin': origin}):
            pytest.fail('Untrusted foreground connection accepted')


def test_focus_contract_rejects_non_boolean_values_and_cleans_up(setup):
    from starlette.websockets import WebSocketDisconnect
    app, _, _, _ = setup
    with client(app).websocket_connect('ws://127.0.0.1:8788/api/desktop/node-windows/focus') as socket:
        socket.send_json({'focused': True})
        socket.receive_json()
        socket.send_json({'focused': 'false'})
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert app.state.node_windows.alerts.status()['focused_pages'] == 0
