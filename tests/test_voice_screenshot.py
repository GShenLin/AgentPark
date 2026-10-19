import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.desktop_capture.contracts import DisplayCatalog, CapturedFrame
from src.providers.agent_runtime_context import AgentRuntimeContext, bind_agent_runtime_context
from src.providers.voice_provider import VoiceCall, RtcVoiceCall
from src.remote_workspace.active_execution import active_node_execution, active_execution_context
from src.web_backend.node_voice import NodeVoiceApi, VoiceLease
from src.web_backend.execution_capture import ExecutionTarget

CATALOG = DisplayCatalog(device_name='Worker A', displays=[dict(id='monitor', label='Monitor', x=0, y=0, width=1920, height=1080, primary=True)])
FRAME = CapturedFrame(display_id='monitor', captured_at='2026-10-13T00:00:00Z', width=800, height=450, image='data:image/jpeg;base64,YQ==')


@pytest.fixture
def api(monkeypatch):
    core = SimpleNamespace(node_ops=SimpleNamespace(require_node_visible=Mock()),
        graph_runtime=SimpleNamespace(_sanitize_graph_id=lambda v: v),
        access_api=SimpleNamespace(message_access_metadata=lambda r: {'_access_client_id': r.headers.get('x-owner', 'owner')}))
    voice = NodeVoiceApi(core)
    for node in ['a', 'b']:
        voice._leases[node] = VoiceLease(node, 'default', 'owner', time.monotonic() + 60,
            call=VoiceCall('sdp', 'voice', 'openai-realtime-v4', screen=Mock(publish=Mock(return_value='exec_frame'))))
    target = Mock(side_effect=lambda node, graph: ExecutionTarget(node, '/work'))
    capture = Mock(side_effect=lambda target, command: CATALOG if command.action == 'displays' else FRAME)
    monkeypatch.setattr(voice.capture, 'target', target)
    monkeypatch.setattr(voice.capture, 'capture', capture)
    app = FastAPI()
    app.post('/voice/{node_id}/{session_id}/screenshot')(voice.screenshot.apply)
    return app, voice, target, capture


@pytest.mark.parametrize('transport', ['webrtc', 'volcengine-rtc'])
def test_one_request_one_capture_direct_to_model_and_retry_reuses_receipt(api, transport):
    app, voice, _, capture = api
    if transport == 'volcengine-rtc':
        for lease in voice._leases.values():
            lease.call = RtcVoiceCall('app', 'room', 'user', 'bot', 'token', 'doubao', Mock(), screen=lease.call.screen)
    capture.assert_not_called()
    with TestClient(app, client=('127.0.0.1', 123)) as client:
        for node in ['a', 'b']:
            route = f'/voice/{node}/{node}/screenshot'
            result = client.post(route, json={'request_id': 'tool-call', 'display_id': ''})
            assert result.status_code == 200
            assert result.json()['delivered'] and result.json()['frame_id'] == 'exec_frame'
            assert FRAME.image not in result.text and 'image' not in result.json()
            assert client.post(route, json={'request_id': 'tool-call', 'display_id': ''}).json() == result.json()
            assert voice._leases[node].call.screen.publish.call_count == 1
            assert capture.call_args.args[0].device_id == node
        assert [call.args[1].action for call in capture.call_args_list] == ['displays','frame','displays','frame']
        assert client.post('/voice/a/a/screen', json={'action': 'prepare'}).status_code == 404


@pytest.mark.parametrize('change', ['device', 'hangup', 'provider-error'])
@pytest.mark.parametrize('phase', ['capture', 'publish'])
def test_inflight_failures_never_register_stale_image_or_end_audio(api, change, phase):
    app, voice, target, capture = api
    lease = voice._leases['a']
    def alter():
        if change == 'device': target.side_effect = lambda *_: ExecutionTarget('other', '/other')
        elif change == 'hangup': lease.close()
        else: raise RuntimeError('image refused')
    if phase == 'capture':
        def grab(_target, command):
            if command.action == 'displays': return CATALOG
            alter()
            return FRAME
        capture.side_effect = grab
    else:
        def publish(*_):
            alter()
            return 'exec_stale'
        lease.call.screen.publish.side_effect = publish
    with TestClient(app, client=('127.0.0.1', 123)) as client:
        response = client.post('/voice/a/a/screenshot', json={'request_id': 'tool'})
    assert response.status_code == 409
    assert not lease.screenshots and FRAME.image not in response.text
    if change != 'hangup': lease.call.screen.close.assert_not_called()


@pytest.mark.parametrize('address,headers,node,graph,status', [
    ('192.168.0.1', {}, 'a', 'default', 403),
    ('127.0.0.1', {'sec-fetch-site': 'cross-site'}, 'a', 'default', 403),
    ('127.0.0.1', {'x-owner': 'another'}, 'a', 'default', 404),
    ('127.0.0.1', {}, 'b', 'default', 404),
    ('127.0.0.1', {}, 'a', 'other', 404),
])
def test_unowned_requests_do_not_capture(api, address, headers, node, graph, status):
    app, _, _, capture = api
    with TestClient(app, client=(address, 123)) as client:
        assert client.post(f'/voice/{node}/a/screenshot?graph_id={graph}', json={'request_id': 'tool'}, headers=headers).status_code == status
    capture.assert_not_called()


def test_acknowledged_screenshot_history_is_bounded(api):
    app, voice, _, _ = api
    lease = voice._leases['a']
    lease.call.screen.publish.side_effect = [f'exec_{n}' for n in range(21)]
    with TestClient(app, client=('127.0.0.1', 123)) as client:
        for n in range(21):
            assert client.post('/voice/a/a/screenshot', json={'request_id': str(n)}).status_code == 200
    assert list(lease.screenshots) == [f'exec_{n}' for n in range(1,21)]
    assert len(lease.screenshot_requests) == 20


def test_unknown_display_and_conflicting_retry_never_capture_wrong_screen(api):
    app, voice, target, capture = api
    with TestClient(app, client=('127.0.0.1', 123)) as client:
        route = '/voice/a/a/screenshot'
        assert client.post(route, json={'request_id': 'bad', 'display_id': 'unknown'}).status_code == 400
        assert all(call.args[1].action == 'displays' for call in capture.call_args_list)
        assert client.post(route, json={'request_id': 'good'}).status_code == 200
        count = capture.call_count
        target.side_effect = lambda *_: ExecutionTarget('other', '/work')
        assert client.post(route, json={'request_id': 'good'}).status_code == 409
        assert capture.call_count == count


def test_target_resolution_prefers_live_run_and_cleans_up_on_error(tmp_path):
    agent = SimpleNamespace()
    context = AgentRuntimeContext(node_directory=str(tmp_path), remote_enabled=True, remote_worker_id='worker-a', working_path='/a')
    bind_agent_runtime_context(agent, context)
    with pytest.raises(RuntimeError, match='test cleanup'):
        with active_node_execution(agent):
            assert active_execution_context(str(tmp_path)).remote_worker_id == 'worker-a'
            bind_agent_runtime_context(agent, replace(context, remote_worker_id='worker-b', working_path='/b'))
            assert active_execution_context(str(tmp_path)).remote_worker_id == 'worker-b'
            agent._execution_device_state.switching = True
            with pytest.raises(RuntimeError, match='切换'):
                active_execution_context(str(tmp_path))
            raise RuntimeError('test cleanup')
    assert active_execution_context(str(tmp_path)) is None


def test_remote_capture_uses_explicit_capability_and_typed_result():
    remote = SimpleNamespace(_wait_online=Mock(return_value={'capabilities': ['desktop_screen']}), _execute=Mock(return_value=CATALOG.model_dump_json()))
    voice = NodeVoiceApi(SimpleNamespace(remote_workspace_api=remote, graph_runtime=SimpleNamespace()))
    from src.desktop_capture.contracts import CaptureRequest
    result = voice.capture.capture(ExecutionTarget('peer:target', '/work'), CaptureRequest(action='displays'))
    assert result == CATALOG
    assert remote._execute.call_args.args[0]['worker_id'] == 'peer:target'
    remote._wait_online.return_value = {'capabilities': []}
    with pytest.raises(RuntimeError, match='更新'):
        voice.capture.capture(ExecutionTarget('peer:target', '/work'), CaptureRequest(action='displays'))


def test_jpeg_encoding_is_bounded_and_keeps_aspect_ratio():
    from PIL import Image
    from src.desktop_capture.windows import encode_frame
    frame = encode_frame(Image.new('RGB', (3840, 2160), 'red'), 'monitor', 64000)
    assert (frame.width, frame.height) == (1600, 900)
    assert len(frame.image) <= 64000


def test_node_target_uses_configuration_only_while_idle(tmp_path):
    import json
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'type_id': 'agent_node', 'provider_id': 'provider', 'remote_enabled': True,
                                  'remote_worker_id': 'configured', 'working_path': '/configured'}), encoding='utf-8')
    voice = NodeVoiceApi(SimpleNamespace(graph_runtime=SimpleNamespace(_node_config_path=lambda *_: str(config))))
    assert voice.capture.target('node', 'default').device_id == 'configured'
    agent = SimpleNamespace()
    bind_agent_runtime_context(agent, AgentRuntimeContext(node_directory=str(tmp_path), remote_enabled=True,
                                                          remote_worker_id='live-device', working_path='/live'))
    with active_node_execution(agent):
        assert voice.capture.target('node', 'default') == ExecutionTarget('live-device', '/live')
    assert voice.capture.target('node', 'default').device_id == 'configured'


def test_dense_screen_is_resized_to_the_actual_channel_budget():
    from PIL import Image
    from src.desktop_capture.windows import encode_frame
    image = Image.effect_noise((1920, 1080), 50).convert('RGB')
    frame = encode_frame(image, 'monitor', 61952)
    assert len(frame.image) <= 61952
    assert 640 <= frame.width < 1600
