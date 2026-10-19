import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.desktop_annotations.contracts import AnnotationDrawing, annotation_tool
from src.providers.voice_provider import VoiceCall
from src.web_backend.node_voice import NodeVoiceApi, VoiceLease
from src.web_backend.execution_capture import ExecutionTarget
from src.web_backend.node_voice_screenshot import VoiceScreenshot
from src.peer_network.principal import CloudBoardAdministrator
from src.desktop_capture.contracts import DisplayCatalog

IDENTITY = 'a' * 32
DRAWING = {'action': 'replace', 'frame_id': 'exec_frame', 'duration_seconds': 10,
           'shapes': [{'kind': 'ellipse', 'x': .2, 'y': .3, 'width': .4, 'height': .2, 'color': 'red'},
                      {'kind': 'text', 'x': .2, 'y': .6, 'text': '点击这里', 'color': 'yellow'}]}


@pytest.fixture
def api(monkeypatch):
    core = SimpleNamespace(node_ops=SimpleNamespace(require_node_visible=Mock()),
        graph_runtime=SimpleNamespace(_sanitize_graph_id=lambda v: v),
        access_api=SimpleNamespace(message_access_metadata=lambda r: {'_access_client_id': r.headers.get('x-owner', 'owner')}))
    voice = NodeVoiceApi(core)
    lease = VoiceLease('node', 'default', 'owner', time.monotonic()+60, call=VoiceCall('sdp', 'voice', 'openai-realtime-v4'))
    voice._leases['session'] = lease
    target = ExecutionTarget('local', '')
    voice.capture.target = Mock(return_value=target)
    catalog = DisplayCatalog(device_name='PC', displays=[dict(id='display', label='Monitor', x=0, y=0, width=1920, height=1080, primary=True)])
    lease.screenshots['exec_frame'] = VoiceScreenshot(target, catalog.displays[0], 800, 450, '2026-10-14T00:00:00Z')
    host = Mock(identity=IDENTITY, displays=[d.model_dump() for d in catalog.displays], target=target)
    host.command.return_value = {'ok': True}
    create = Mock(return_value=host)
    monkeypatch.setattr('src.web_backend.node_voice_annotations.ExecutionAnnotationHost', create)
    app = FastAPI()
    app.post('/voice/{node_id}/{session_id}/annotations')(voice.annotations.apply)
    return app, voice, host, create


def test_first_drawing_opens_overlay_without_enable_or_sharing_and_hangup_closes(api):
    app, voice, host, create = api
    with TestClient(app, client=('127.0.0.1', 123)) as client:
        route = '/voice/node/session/annotations'
        for _ in range(2): assert client.post(route, json=DRAWING).status_code == 200
        create.assert_called_once()
        assert host.command.call_args.args[0]['display_id'] == 'display'
        assert host.command.call_args.args[0]['drawing'] == DRAWING
        voice._leases['session'].close()
        host.close.assert_called_once()
        assert client.post(route, json=DRAWING).status_code == 409


@pytest.mark.parametrize('case', ['unknown-image', 'empty-image', 'wrong-device', 'native-failure'])
def test_bad_drawing_is_reported_without_closing_voice(api, case):
    app, voice, host, create = api
    drawing = dict(DRAWING)
    if case == 'unknown-image': drawing['frame_id'] = 'unknown'
    elif case == 'empty-image': drawing['frame_id'] = ''
    elif case == 'wrong-device': voice.capture.target.return_value = ExecutionTarget('other', '/work')
    else: host.command.side_effect = RuntimeError('native drawing failed')
    with TestClient(app, client=('127.0.0.1', 123)) as client:
        assert client.post('/voice/node/session/annotations', json=drawing).status_code == 409
    assert voice._leases['session'].finished is None
    if case != 'native-failure': create.assert_not_called()


def test_clear_without_a_screenshot_does_not_open_native_overlay(api):
    app, voice, host, create = api
    voice._leases['session'].screenshots.clear()
    with TestClient(app, client=('127.0.0.1', 123)) as client:
        assert client.post('/voice/node/session/annotations', json={**DRAWING, 'action':'clear','frame_id':'','shapes':[]}).status_code == 200
    create.assert_not_called()


def test_cloud_owner_draws_directly_and_cross_site_request_is_rejected(api):
    app, voice, host, create = api
    @app.middleware('http')
    async def principal(request, next_handler):
        request.state.peer_principal = CloudBoardAdministrator('peer', 'owner')
        return await next_handler(request)
    with TestClient(app, client=('portal:owner', 0)) as client:
        assert client.post('/voice/node/session/annotations', json=DRAWING, headers={'origin':'https://47.109.29.75'}).status_code == 200
        assert client.post('/voice/node/session/annotations', json=DRAWING, headers={'sec-fetch-site':'cross-site'}).status_code == 403


@pytest.mark.parametrize('update', [
    {'duration_seconds': 0}, {'duration_seconds': 61}, {'duration_seconds': True},
    {'action': 'replace', 'shapes': []}, {'action': 'clear'},
    {'shapes': [{'kind': 'text', 'x': -1, 'y': 0, 'text': 'x', 'color': 'red'}]},
    {'shapes': [{'kind': 'text', 'x': 0, 'y': 0, 'text': '<x>', 'color': 'red', 'html': True}]},
])
def test_annotation_contract_rejects_out_of_bounds_and_unstructured_data(update):
    with pytest.raises(ValidationError):
        AnnotationDrawing.model_validate({**DRAWING, **update})


def test_provider_schema_has_no_unresolved_refs_and_keeps_bounded_shapes():
    tool = annotation_tool()
    assert tool['name'] == 'annotate_screen'
    assert '$ref' not in str(tool)
    assert tool['parameters']['properties']['shapes']['maxItems'] == 12
    assert tool['parameters']['additionalProperties'] is False


def test_partial_ellipse_is_clipped_by_renderer_not_rejected():
    value = {**DRAWING, 'frame_id': '', 'shapes': [dict(kind='ellipse', x=.9, y=.9, width=.3, height=.3, color='red')]}
    assert AnnotationDrawing.model_validate(value).frame_id == ''
