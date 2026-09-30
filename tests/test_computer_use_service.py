import json
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from src.computer_use.contracts import ComputerUseError
from src.computer_use.service import ComputerUseService
from src.runtime_cancellation import CancellationRequested


WINDOW = {'id': 5, 'app': 'process:C:\\demo.exe', 'pid': 10, 'process_started': 'now', 'title': 'Demo'}


class Backend:
    def __init__(self):
        self.window = WINDOW.copy()
        self.rect = (-800, 100, 0, 700)
        self.actions = []
        self.fail = False

    def list_windows(self): return [self.window.copy()]
    def list_apps(self): return [{'id': self.window['app'], 'windows': self.list_windows()}]
    def resolve(self, window): return self.window.copy()
    def rectangle(self, window): return self.rect
    def observe(self, window, include_text, limit, cancel):
        elements = [{'index': 0, 'runtime_id': [1], 'name': 'Edit'}] if include_text else []
        return {'elements': elements, 'focus': [1], 'accessibility': {'elements': elements} if include_text else None}
    def capture(self, window, cancel, mode): return Image.new('RGB', (800, 600))
    def activate(self, window): self.actions.append('activate')
    def launch(self, app): self.actions.append('launch')
    def act(self, method, window, observation, args, cancel):
        self.actions.append(method)
        if self.fail: raise ComputerUseError('input failed')


@pytest.fixture
def desktop():
    backend = Backend()
    return ComputerUseService(backend), backend


def observe(service, owner='one', **kwargs):
    return service.call('get_window_state', owner, {'window': WINDOW, 'settle_ms': 0, **kwargs})


def click(service, state, owner='one'):
    return service.call('click', owner, {'window': WINDOW, 'observation_id': state['observation_id'], 'x': 20, 'y': 30})


def test_observe_delivers_image_and_window_coordinate_origin(desktop):
    service, _ = desktop
    state = observe(service, include_text=True)
    assert state['bounds'] == {'left': -800, 'top': 100, 'right': 0, 'bottom': 700}
    assert state['screenshotId'] == state['observation_id']
    assert (state['width'], state['height'], state['mime_type']) == (800, 600, 'image/png')
    from src.tool.tool_result_processing import process_tool_result_outcome
    result = process_tool_result_outcome(json.dumps({'status': 'success', **state}))
    assert result.images[0]['base64'] == state['screenshots'][0]['base64_image']
    assert json.loads(result.cleaned_result)['observation_id'] == state['observation_id']


def test_popup_context_and_native_focus_reach_the_model_and_observation(desktop, monkeypatch):
    service, backend = desktop
    focus = {'focus_id': 5, 'active_id': 5, 'foreground_id': 5}
    popup = {**WINDOW, 'id': 6, 'title': ''}
    monkeypatch.setattr(backend, 'observe', lambda *args: {
        'native_focus': focus, 'related_windows': [popup], 'focus': [1], 'elements': []})
    state = observe(service)
    assert state['native_focus'] == focus
    assert state['related_windows'] == [popup]
    assert service.observations[state['observation_id']].native_focus == focus


def test_visible_region_capture_is_explicit_and_never_an_error_fallback(desktop, monkeypatch):
    service, backend = desktop
    modes = []
    def capture(window, cancel, mode):
        modes.append(mode)
        if mode == 'window':
            raise ComputerUseError('WGC rejected tool window')
        return Image.new('RGB', (800, 600))
    monkeypatch.setattr(backend, 'capture', capture)
    with pytest.raises(ComputerUseError, match='WGC rejected'):
        observe(service)
    assert modes == ['window']
    assert not service.observations
    state = observe(service, capture_mode='visible_region')
    assert state['capture_scope'] == 'visible_screen_region'
    assert modes == ['window', 'visible_region']
    with pytest.raises(ComputerUseError, match='capture_mode'):
        observe(service, capture_mode='automatic')


def test_input_receipt_does_not_claim_task_result_verified(desktop):
    service, _ = desktop
    result = click(service, observe(service))
    assert result['input_dispatched'] is True
    assert result['result_verified'] is False


def test_input_receipt_survives_popup_closing_during_click(desktop, monkeypatch):
    service, backend = desktop
    state = observe(service)
    def closed(window):
        raise ComputerUseError('Window no longer exists')
    def act(*args):
        monkeypatch.setattr(backend, 'resolve', closed)
    monkeypatch.setattr(backend, 'act', act)
    assert click(service, state)['input_dispatched'] is True


@pytest.mark.parametrize('reason', ['used', 'expired', 'other_owner', 'moved', 'process_reused', 'new_observation', 'other_agent_input'])
def test_stale_observation_cannot_dispatch_input(desktop, reason):
    service, backend = desktop
    state = observe(service)
    owner = 'one'
    if reason == 'used': click(service, state)
    elif reason == 'expired': service.clock = lambda: float('inf')
    elif reason == 'other_owner': owner = 'two'
    elif reason == 'moved': backend.rect = (0, 0, 800, 600)
    elif reason == 'process_reused': backend.window['process_started'] = 'later'
    elif reason == 'new_observation': observe(service)
    elif reason == 'other_agent_input': click(service, observe(service, 'two'), 'two')
    before = list(backend.actions)
    with pytest.raises(ComputerUseError): click(service, state, owner)
    assert backend.actions == before


def test_failure_consumes_observation(desktop):
    service, backend = desktop
    state = observe(service)
    backend.fail = True
    with pytest.raises(ComputerUseError, match='input failed'): click(service, state)
    with pytest.raises(ComputerUseError, match='consumed'): click(service, state)
    assert backend.actions == ['click']


def test_coordinate_action_requires_image_but_element_action_does_not(desktop):
    service, _ = desktop
    state = observe(service, include_screenshot=False, include_text=True)
    with pytest.raises(ComputerUseError, match='screenshot observation'): click(service, state)
    result = service.call('set_value', 'one', {'window': WINDOW, 'observation_id': state['observation_id'], 'element_index': 0, 'value': 'text'})
    assert result['action'] == 'set_value'


def test_app_discovery_and_launch(desktop):
    service, backend = desktop
    assert service.call('list_windows', 'one', {}) == {'windows': backend.list_windows()}
    assert service.call('list_apps', 'one', {}) == {'apps': backend.list_apps()}
    result = service.call('launch_app', 'one', {'app': WINDOW['app']})
    assert result['launched'] == WINDOW['app']
    assert backend.actions == ['launch']


def test_cancellation_prevents_dispatch_and_interrupts_lock_wait(desktop):
    service, backend = desktop
    event = threading.Event()
    event.set()
    with pytest.raises(CancellationRequested): service.call('list_windows', 'one', {}, event)
    with service.lock:
        with pytest.raises(CancellationRequested): service.call('list_windows', 'one', {}, event)
    assert backend.actions == []


def test_tool_registration_and_agent_observation_ownership(monkeypatch, desktop):
    from src.tool.base_tool import BaseTool
    from src.computer_use import runtime
    monkeypatch.setattr(runtime, '_service', desktop[0])
    first, second = SimpleNamespace(config={}), SimpleNamespace(config={})
    tools = BaseTool(first)
    tools.addTool('computer_use_tools')
    state = json.loads(tools.execute_tool('get_window_state', {'window': WINDOW}))
    assert state['status'] == 'success'
    other = BaseTool(second)
    other.addTool('computer_use_tools')
    result = json.loads(other.execute_tool('click', {'window': WINDOW, 'observation_id': state['observation_id'], 'x': 20, 'y': 20}))
    assert result['status'] == 'error'
    assert desktop[1].actions == []


def test_unicode_uses_utf16_native_input_and_releases_on_cancel(monkeypatch):
    from src.computer_use import windows_input
    calls = []
    monkeypatch.setattr(windows_input, 'key_event', lambda **kw: calls.append(kw))
    windows_input.literal_text('\u4e2d\u6587\U0001f600', None, lambda: None)
    assert [v['scan'] for v in calls[::2]] == [0x4E2D, 0x6587, 0xD83D, 0xDE00]
    assert all(v['flags'] == 6 for v in calls[1::2])
    event = threading.Event()
    def key_event(**kw):
        calls.append(kw)
        event.set()
    monkeypatch.setattr(windows_input, 'key_event', key_event)
    with pytest.raises(CancellationRequested): windows_input.literal_text('a', event, lambda: None)
    assert calls[-1] == {'scan': 97, 'flags': 6}


def test_chord_releases_pressed_modifiers_on_error(monkeypatch):
    from src.computer_use import windows_input
    calls = []
    monkeypatch.setattr(windows_input, 'key_event', lambda **kw: calls.append(kw))
    def guard():
        if calls: raise ComputerUseError('focus changed')
    with pytest.raises(ComputerUseError): windows_input.chord('Control_L+a', None, guard)
    assert calls == [{'vk': 0xA2}, {'vk': 0xA2, 'flags': 2}]


def test_failed_refresh_discards_previous_observation(desktop, monkeypatch):
    service, backend = desktop
    state = observe(service)
    def fail(*args): raise ComputerUseError('capture failed')
    monkeypatch.setattr(backend, 'capture', fail)
    with pytest.raises(ComputerUseError, match='capture failed'): observe(service)
    with pytest.raises(ComputerUseError, match='consumed'): click(service, state)
    assert not backend.actions


def test_shared_desktop_epoch_invalidates_other_process_observation():
    from contextlib import nullcontext
    class Shared:
        generation = 0
        def access(self, cancel): return nullcontext()
        def epoch(self): return self.generation
        def bump(self): self.generation += 1
    shared = Shared()
    first_backend, second_backend = Backend(), Backend()
    first_backend.desktop_session = second_backend.desktop_session = shared
    first, second = ComputerUseService(first_backend), ComputerUseService(second_backend)
    before = observe(first)
    click(second, observe(second))
    with pytest.raises(ComputerUseError, match='consumed'): click(first, before)
    assert not first_backend.actions


def test_native_tool_configured_timeout_waits_for_cleanup(monkeypatch, desktop):
    import time
    from src.computer_use import runtime
    from src.runtime_cancellation import raise_if_cancel_requested
    from src.tool.base_tool import BaseTool
    cleaned = threading.Event()
    service, backend = desktop
    monkeypatch.setattr(runtime, '_service', service)
    def act(method, window, observation, args, cancel):
        try:
            while True:
                raise_if_cancel_requested(cancel)
                time.sleep(0.005)
        finally:
            time.sleep(0.06)
            cleaned.set()
    monkeypatch.setattr(backend, 'act', act)
    agent = SimpleNamespace(config={'toolExecutionTimeoutSecByName': {'click': 0.02}})
    tools = BaseTool(agent)
    tools.addTool('computer_use_tools')
    state = json.loads(tools.execute_tool('get_window_state', {'window': WINDOW}))
    result = json.loads(tools.execute_tool('click', {'window': WINDOW,
        'observation_id': state['observation_id'], 'x': 10, 'y': 20}))
    assert result['status'] == 'timeout'
    assert cleaned.is_set()
    assert not service.observations
