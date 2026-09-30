import json
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from src.computer_use.contracts import ComputerUseError
from src.computer_use.service import ComputerUseService
from src.runtime_cancellation import CancellationRequested


ROOT = {'id': 10, 'app': 'process:C:\\editor.exe', 'pid': 100,
        'process_started': 'now', 'title': 'Editor'}


class Scene:
    def __init__(self):
        self.windows = {10: ROOT.copy()}
        self.calls = []
        self.capture_error = None
        self.after_input = lambda: None

    def popup(self, hwnd=20):
        self.windows[hwnd] = {**ROOT, 'id': hwnd, 'title': '', 'is_tool_window': True}

    def resolve(self, window):
        if window['id'] not in self.windows:
            raise ComputerUseError('Window closed')
        return self.windows[window['id']].copy()

    def list_windows(self): return list(self.windows.values())
    def rectangle(self, window): return (100, 100, 180, 160)

    def observe(self, window, include_text, limit, cancel):
        popups = [w for w in self.windows.values() if w['id'] != 10 and w['id'] != window['id']]
        return {'related_windows': popups, 'transient_windows': popups,
                'focus': [window['id']], 'elements': [], 'native_focus': {'focus_id': window['id']}}

    def capture(self, window, cancel, mode):
        self.calls.append(('capture', window['id'], mode))
        if self.capture_error and self.capture_error[0] == window['id']:
            raise self.capture_error[1]
        return Image.new('RGB', (80, 60), 'red' if len(self.windows) > 1 else 'blue')

    def act(self, action, window, observation, args, cancel):
        self.calls.append(('input', window['id']))
        self.after_input()


def observe(service, **args):
    return service.call('get_window_state', 'agent', {'window': ROOT, 'settle_ms': 0, **args})


def click(service, state):
    return service.call('click', 'agent', {'window': state['window'],
                        'observation_id': state['observation_id'], 'x': 10, 'y': 10})


def test_action_returns_new_usable_observation_without_second_model_call():
    scene = Scene()
    service = ComputerUseService(scene)
    before = observe(service)
    scene.after_input = scene.popup
    after = click(service, before)
    assert after['input_dispatched'] and after['observation_available']
    assert after['observation_id'] != before['observation_id']
    assert len(after['screenshots']) == 2
    assert after['screenshots'][0]['base64_image'] != before['screenshots'][0]['base64_image']
    popup = after['related_states'][0]
    assert popup['capture_scope'] == 'visible_screen_region'
    scene.after_input = lambda: scene.windows.pop(20)
    closed = click(service, popup)
    assert closed['input_window']['id'] == 20
    assert closed['window']['id'] == 10
    assert len(closed['screenshots']) == 1
    assert ('capture', 20, 'visible_region') in scene.calls
    with pytest.raises(ComputerUseError, match='consumed'):
        click(service, before)


@pytest.mark.parametrize('error', [ComputerUseError('capture failed'), RuntimeError('COM failed')])
def test_refresh_failure_reports_input_already_sent_and_cannot_replay(error):
    scene = Scene()
    service = ComputerUseService(scene)
    before = observe(service)
    scene.after_input = lambda: setattr(scene, 'capture_error', (10, error))
    result = click(service, before)
    assert result['status'] == 'error'
    assert result['phase'] == 'post_action_observation'
    assert result['input_dispatched'] is True
    assert result['observation_available'] is False
    assert str(error) in result['error']
    assert not service.observations
    with pytest.raises(ComputerUseError, match='consumed'):
        click(service, before)
    assert scene.calls.count(('input', 10)) == 1


def test_popup_capture_error_is_explicit_and_never_creates_input_token():
    scene = Scene()
    scene.popup()
    scene.capture_error = (20, ComputerUseError('popup hidden'))
    service = ComputerUseService(scene)
    state = observe(service)
    assert state['related_states'] == [{'window': scene.windows[20], 'observation_error': 'popup hidden'}]
    assert len(service.observations) == 1
    assert len(state['screenshots']) == 1


def test_multiwindow_capture_is_bounded_and_omissions_are_visible():
    scene = Scene()
    for hwnd in range(20, 25):
        scene.popup(hwnd)
    service = ComputerUseService(scene)
    state = observe(service)
    assert len(state['screenshots']) == 4
    assert state['omitted_window_ids'] == [23, 24]
    only_root = observe(service, include_related=False)
    assert len(only_root['screenshots']) == 1
    assert len(service.observations) == 1


def test_sibling_observation_cannot_be_used_for_other_window():
    scene = Scene()
    scene.popup()
    service = ComputerUseService(scene)
    state = observe(service)
    popup = state['related_states'][0]
    with pytest.raises(ComputerUseError, match='another window'):
        click(service, {**popup, 'window': ROOT})


def test_settling_delay_is_explicit_inherited_and_cancellable(monkeypatch):
    from src.computer_use import observations
    delays = []
    monkeypatch.setattr(observations, 'sleep_with_cancel', lambda duration, cancel: delays.append(duration))
    service = ComputerUseService(Scene())
    result = click(service, observe(service, settle_ms=350))
    assert delays == [0.35, 0.35]
    assert result['settle_ms'] == 350 and not result['render_complete_verified']
    with pytest.raises(ComputerUseError, match='settle_ms'):
        observe(service, settle_ms=4000)


def test_cancellation_after_input_leaves_no_usable_observation():
    scene = Scene()
    service = ComputerUseService(scene)
    state = observe(service)
    event = threading.Event()
    scene.after_input = event.set
    with pytest.raises(CancellationRequested):
        service.call('click', 'agent', {'window': ROOT, 'observation_id': state['observation_id'],
                                      'x': 1, 'y': 1}, event)
    assert not service.observations


def test_all_screenshot_images_reach_model_with_identity_and_no_base64_in_text():
    from src.providers.responses_followup import build_responses_followup_items
    from src.tool.tool_result_processing import process_tool_result_outcome
    from src.tool.tool_call_protocol import ToolCallExecution
    from src.base_agent import BaseAgent
    scene = Scene()
    scene.popup()
    state = observe(ComputerUseService(scene))
    processed = process_tool_result_outcome(json.dumps(state))
    assert len(processed.images) == 2
    for shot in state['screenshots']:
        assert shot['base64_image'] not in processed.cleaned_result
    execution = ToolCallExecution('click', 'call-1', processed.cleaned_result, images=processed.images)
    agent = SimpleNamespace(Message=lambda *a, **kw: None,
                            _responses_tool_output=lambda e: e.cleaned_result,
                            _build_non_retryable_tool_warning=lambda *a: None,
                            _validate_responses_followup_call_id=lambda call_id: None)
    followup = build_responses_followup_items(agent, [execution])
    assert len(followup) == 3
    assert 'window 10' in followup[1]['content'][0]['text']
    assert 'window 20' in followup[2]['content'][0]['text']
    assert BaseAgent._append_tool_execution_messages_then_warnings(agent, [execution]) == list(processed.images)


def test_registered_input_tool_returns_all_images_and_fresh_tokens(monkeypatch):
    from src.computer_use import runtime
    from src.tool.base_tool import BaseTool
    from src.tool.tool_call_protocol import ToolCallEnvelope
    scene = Scene()
    service = ComputerUseService(scene)
    monkeypatch.setattr(runtime, '_service', service)
    tools = BaseTool(SimpleNamespace(config={}))
    tools.addTool('computer_use_tools')
    before = json.loads(tools.execute_tool('get_window_state', {'window': ROOT, 'settle_ms': 0}))
    scene.after_input = scene.popup
    args = {'window': ROOT, 'observation_id': before['observation_id'], 'x': 5, 'y': 5}
    execution = tools.execute_tool_call(ToolCallEnvelope('click', 'click-1', args, json.dumps(args), 'responses'))
    after = json.loads(execution.cleaned_result)
    assert execution.status == 'completed'
    assert len(execution.images) == 2
    assert after['observation_id'] in service.observations
    assert before['observation_id'] not in service.observations
    assert all(s['base64_image'] == '<base64_image_data_truncated>' for s in after['screenshots'])
