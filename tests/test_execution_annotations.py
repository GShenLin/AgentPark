from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.desktop_annotations.execution import ExecutionAnnotations, ExecutionAnnotationCommand, ExecutionAnnotationResult
from src.desktop_capture.contracts import DisplayCatalog
from src.web_backend.execution_annotations import ExecutionAnnotationHost
from src.web_backend.execution_capture import ExecutionTarget


def catalog():
    return DisplayCatalog(device_name='PC', displays=[dict(id='capture', label='Right screen',
        x=1920, y=-200, width=2560, height=1440, primary=False)])


@pytest.fixture
def service(monkeypatch):
    host = Mock(identity='a' * 32, displays=[dict(id='native',
        physical_bounds=dict(x=1920, y=-200, width=2560, height=1440))])
    host.process.poll.return_value = None
    create = Mock(return_value=host)
    monkeypatch.setattr('src.desktop_annotations.execution.AnnotationHost', create)
    capture = Mock(return_value=catalog())
    monkeypatch.setattr('src.desktop_annotations.execution.displays', capture)
    return ExecutionAnnotations(), host, capture


def test_maps_capture_pixels_to_native_display_and_rejects_changed_layout(service):
    instance, host, capture = service
    ready = instance.execute(ExecutionAnnotationCommand(action='prepare'))
    command = ExecutionAnnotationCommand(action='draw', annotation_id=ready.annotation_id, display_id='capture',
        drawing=dict(action='replace', frame_id='', duration_seconds=5,
                     shapes=[dict(kind='ellipse', x=.9, y=.9, width=.2, height=.2, color='red')]))
    instance.execute(command)
    assert host.command.call_args.args[0]['display_id'] == 'native'
    capture.return_value = catalog().model_copy(update={'displays': []})
    with pytest.raises(ValueError, match='布局'):
        instance.execute(command)
    host.close.assert_called_once()


def test_mismatched_physical_mapping_closes_only_new_host(service):
    instance, host, _ = service
    host.displays[0]['physical_bounds']['x'] = 0
    with pytest.raises(RuntimeError, match='坐标不匹配'):
        instance.execute(ExecutionAnnotationCommand(action='prepare'))
    host.close.assert_called_once()
    assert not instance._hosts


def test_routes_annotation_to_explicit_remote_target_without_local_fallback(monkeypatch):
    local = Mock()
    monkeypatch.setattr('src.web_backend.execution_annotations.execution_annotations', local)
    result = ExecutionAnnotationResult(annotation_id='b' * 32, displays=catalog().displays)
    remote = SimpleNamespace(_wait_online=Mock(return_value={'capabilities': ['desktop_annotations']}),
                             _execute=Mock(return_value=result.model_dump_json()))
    voice = SimpleNamespace(core=SimpleNamespace(remote_workspace_api=remote))
    host = ExecutionAnnotationHost(voice, ExecutionTarget('peer:other', '/work'))
    host.command({'action': 'ping', 'annotation_id': 'b' * 32})
    assert all(call.args[0]['worker_id'] == 'peer:other' for call in remote._execute.call_args_list)
    assert remote._execute.call_args.args[0]['tool_name'] == 'desktop_annotations'
    local.execute.assert_not_called()
    remote._wait_online.return_value = {'capabilities': []}
    with pytest.raises(RuntimeError, match='更新'):
        ExecutionAnnotationHost(voice, ExecutionTarget('peer:old', '/work'))
    local.execute.assert_not_called()
