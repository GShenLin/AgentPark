import base64
import io
import json

import pytest
from PIL import Image, ImageColor

from src.computer_use.action_overlay import annotate_action, COLORS
from src.computer_use.contracts import PointerFeedback, PointerPoint
from src.computer_use.service import ComputerUseService
from src.tool.tool_result_processing import process_tool_result_outcome


def test_native_scale_centers_and_ten_pixel_ruler():
    original = Image.new('RGB', (300, 200), '#263238')
    feedback = PointerFeedback((PointerPoint('start', -450, 170), PointerPoint('end', -280, 220)))
    marked, info = annotate_action(original, (-500, 100, -200, 300), feedback)
    assert marked.size == original.size
    assert original.getpixel((50, 70)) == ImageColor.getrgb('#263238')
    assert marked.getpixel((50, 70)) == ImageColor.getrgb(COLORS['start'])
    assert marked.getpixel((220, 120)) == ImageColor.getrgb(COLORS['end'])
    assert [(p['x'], p['y']) for p in info['points']] == [(50, 70), (220, 120)]
    ruler = info['ruler']
    ox, oy = ruler['origin_x'], ruler['origin_y']
    for offset in range(0, 51, 10):
        assert marked.getpixel((ox + offset, oy + 3)) == (255, 255, 255)
        assert marked.getpixel((ox - 3, oy - offset)) == (255, 255, 255)
    assert marked.getpixel((ox + 5, oy + 3)) == original.getpixel((ox + 5, oy + 3))


@pytest.mark.parametrize('xy', [(0, 0), (99, 0), (0, 99), (99, 99), (10, 88)])
def test_edge_or_ruler_never_displaces_or_hides_center(xy):
    image = Image.new('RGB', (100, 100))
    marked, info = annotate_action(image, (0, 0, 100, 100),
                                  PointerFeedback((PointerPoint('click', *xy),)))
    assert marked.getpixel(xy) == ImageColor.getrgb(COLORS['click'])
    assert info['points'][0]['visible']


def test_small_frame_reports_missing_ruler_and_offscreen_point_without_clamping():
    image = Image.new('RGB', (40, 40), 'blue')
    marked, info = annotate_action(image, (100, 100, 140, 140),
                                  PointerFeedback((PointerPoint('click', 99, 110),)))
    assert marked.tobytes() == image.tobytes()
    assert info['points'][0]['x'] == -1 and not info['points'][0]['visible']
    assert not info['ruler']['drawn'] and info['ruler']['omitted_reason']


ROOT = {'id': 1, 'app': 'editor', 'pid': 1, 'process_started': 'now'}
POPUP = {**ROOT, 'id': 2, 'is_tool_window': True}


class Scene:
    def __init__(self):
        self.popup = True
        self.fail_capture = False

    def resolve(self, window): return window.copy()
    def rectangle(self, window):
        return (-200, 100, 100, 300) if window['id'] == 1 else (-100, 140, 0, 240)

    def observe(self, window, *args):
        return {'transient_windows': [POPUP] if self.popup and window['id'] == 1 else []}

    def capture(self, window, *args):
        if self.fail_capture:
            raise RuntimeError('capture failed')
        rect = self.rectangle(window)
        return Image.new('RGB', (rect[2] - rect[0], rect[3] - rect[1]), 'blue')

    def act(self, action, window, observation, args, cancel):
        if action == 'press_key':
            return None
        rect = self.rectangle(window)
        self.popup = False
        x, y = (20, 30) if args.get('element_index') is not None else (args['x'], args['y'])
        return PointerFeedback((PointerPoint('click', rect[0] + x, rect[1] + y),))


def observe(service, **args):
    return service.call('get_window_state', 'a', {'window': ROOT, 'settle_ms': 0, **args})


def test_popup_click_maps_to_parent_and_annotation_reaches_provider_image():
    scene = Scene()
    service = ComputerUseService(scene)
    before = observe(service)
    assert all('action_overlay' not in s for s in before['screenshots'])
    popup = before['related_states'][0]
    after = service.call('click', 'a', {'window': POPUP, 'observation_id': popup['observation_id'],
                                      'x': 20, 'y': 30})
    shot = after['screenshots'][0]
    assert after['input_window']['id'] == 2 and shot['window']['id'] == 1
    assert shot['action_overlay']['points'][0] == {
        'role': 'click', 'screen_x': -80, 'screen_y': 170, 'x': 120, 'y': 70, 'visible': True}
    processed = process_tool_result_outcome(after)
    image = Image.open(io.BytesIO(base64.b64decode(processed.images[0]['base64'])))
    assert image.size == (300, 200)
    assert image.getpixel((120, 70)) == ImageColor.getrgb(COLORS['click'])
    assert 'NOT verified hits' in processed.images[0]['label']
    assert json.loads(processed.cleaned_result)['screenshots'][0]['action_overlay'] == shot['action_overlay']
    assert 'action_overlay' not in observe(service)['screenshots'][0]


def test_keyboard_and_text_only_observations_do_not_invent_markers():
    service = ComputerUseService(Scene())
    state = observe(service)
    after = service.call('press_key', 'a', {'window': ROOT, 'observation_id': state['observation_id'], 'key': 'Return'})
    assert all('action_overlay' not in s for s in after['screenshots'])
    state = observe(service, include_screenshot=False, include_text=True)
    after = service.call('click', 'a', {'window': ROOT, 'observation_id': state['observation_id'],
                                      'element_index': 0})
    assert after['screenshots'] == []
    assert after['dispatched_pointer_points'][0]['screen_x'] == -180


def test_capture_failure_preserves_dispatched_position_and_consumes_token():
    scene = Scene()
    service = ComputerUseService(scene)
    state = observe(service)
    scene.fail_capture = True
    after = service.call('click', 'a', {'window': ROOT, 'observation_id': state['observation_id'], 'x': 10, 'y': 20})
    assert after['phase'] == 'post_action_observation'
    assert after['dispatched_pointer_points'] == [{'role': 'click', 'screen_x': -190, 'screen_y': 120}]
    assert not service.observations


def test_post_action_window_move_uses_new_frame_origin(monkeypatch):
    scene = Scene()
    service = ComputerUseService(scene)
    state = observe(service)
    original_act = scene.act

    def move_after_input(*args):
        feedback = original_act(*args)
        monkeypatch.setattr(scene, 'rectangle', lambda window: (-180, 110, 120, 310))
        return feedback

    monkeypatch.setattr(scene, 'act', move_after_input)
    after = service.call('click', 'a', {'window': ROOT, 'observation_id': state['observation_id'], 'x': 50, 'y': 60})
    point = after['screenshots'][0]['action_overlay']['points'][0]
    assert (point['screen_x'], point['screen_y']) == (-150, 160)
    assert (point['x'], point['y']) == (30, 50)


def test_multi_image_overlays_use_each_images_origin(monkeypatch):
    scene = Scene()
    service = ComputerUseService(scene)
    state = observe(service)
    monkeypatch.setattr(scene, 'act', lambda *args: PointerFeedback((PointerPoint('click', -80, 170),)))
    after = service.call('click', 'a', {'window': ROOT, 'observation_id': state['observation_id'], 'x': 120, 'y': 70})
    assert [(s['action_overlay']['points'][0]['x'], s['action_overlay']['points'][0]['y'])
            for s in after['screenshots']] == [(120, 70), (20, 30)]


def test_render_preview(tmp_path):
    from PIL import ImageDraw
    image = Image.new('RGB', (640, 320), '#202020')
    draw = ImageDraw.Draw(image)
    for x in range(0, 640, 20):
        draw.line((x, 0, x, 320), fill='#303030')
    for y in range(0, 320, 20):
        draw.line((0, y, 640, y), fill='#303030')
    draw.rounded_rectangle((70, 65, 240, 145), radius=8, outline='white', width=2)
    draw.text((85, 80), 'Example source', fill='white')
    draw.polygon(((220, 116), (228, 120), (220, 124)), outline='white')
    draw.rounded_rectangle((410, 130, 590, 220), radius=8, outline='white', width=2)
    draw.text((430, 145), 'Example target', fill='white')
    marked, _ = annotate_action(image, (0, 0, 640, 320), PointerFeedback((
        PointerPoint('start', 230, 100), PointerPoint('end', 420, 180))))
    path = tmp_path / 'pointer-feedback-preview.png'
    marked.save(path)
    print(f'OVERLAY_PREVIEW={path}')


@pytest.mark.parametrize('action,element_index', [('click', None), ('click', 0), ('drag', None), ('scroll', None)])
def test_windows_backend_reports_coordinates_actually_passed_to_input(monkeypatch, action, element_index):
    gui = pytest.importorskip('win32gui')
    api = pytest.importorskip('win32api')
    from types import SimpleNamespace
    from src.computer_use import windows_backend as mod
    backend = mod.WindowsBackend.__new__(mod.WindowsBackend)
    rect = (-500, 100, -200, 300)
    monkeypatch.setattr(backend, 'rectangle', lambda window: rect)
    monkeypatch.setattr(backend, 'resolve', lambda window: window)
    monkeypatch.setattr(backend, '_desktop_available', lambda: None)
    monkeypatch.setattr(gui, 'GetForegroundWindow', lambda: 1)
    monkeypatch.setattr(gui, 'WindowFromPoint', lambda point: 1)
    monkeypatch.setattr(gui, 'GetAncestor', lambda hwnd, flag: 1)
    monkeypatch.setattr(mod.native, 'accepts_pointer', lambda *args: True)
    sent = []
    monkeypatch.setattr(mod.inputs, 'click', lambda point, *args: sent.append(point))
    monkeypatch.setattr(mod.inputs, 'drag', lambda start, end, *args: sent.extend([start, end]))
    monkeypatch.setattr(api, 'SetCursorPos', sent.append)
    monkeypatch.setattr(mod.inputs, 'mouse_event', lambda *args: None)
    monkeypatch.setattr(mod.uia, 'element_action', lambda *args: (-400, 150))
    args = {'x': 30, 'y': 40, 'from_x': 20, 'from_y': 30, 'to_x': 80, 'to_y': 90, 'scrollY': 120}
    if element_index is not None:
        args = {'element_index': element_index}
    feedback = backend.act(action, ROOT, SimpleNamespace(rect=rect, elements=[{}]), args, None)
    assert [(p.screen_x, p.screen_y) for p in feedback.points] == sent
    assert sent == ([(-480, 130), (-420, 190)] if action == 'drag' else
                    [(-400, 150)] if element_index is not None else [(-470, 140)])
