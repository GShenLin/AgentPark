"""Bounded multi-window snapshots and their exact per-window input credentials."""
import base64
import io
import uuid

from src.runtime_cancellation import raise_if_cancel_requested, sleep_with_cancel
from .contracts import ComputerUseError, Observation, integer
from .action_overlay import annotate_action


MAX_SCREENSHOTS = 4


def observation_options(args):
    options = {key: args.get(key, default) for key, default in (
        ('include_text', False), ('include_screenshot', True),
        ('include_related', True), ('capture_mode', 'window'),
        ('max_elements', 200), ('settle_ms', 200))}
    for key in ('include_text', 'include_screenshot', 'include_related'):
        if not isinstance(options[key], bool):
            raise ComputerUseError(f'{key} must be a boolean')
    if not options['include_text'] and not options['include_screenshot']:
        raise ComputerUseError('Request a screenshot, accessibility text, or both.')
    if options['capture_mode'] not in ('window', 'visible_region'):
        raise ComputerUseError('capture_mode must be window or visible_region')
    integer(options['max_elements'], 'max_elements', 1, 500)
    integer(options['settle_ms'], 'settle_ms', 0, 3000)
    return options


def collect_observations(backend, owner, window, options, cancel, *, clock, generation, ttl, pointer_feedback=None):
    # An explicit settling delay, not a claim that animations/background work ended.
    sleep_with_cancel(options['settle_ms'] / 1000, cancel)
    observations = {}
    screenshots = []

    def capture(target, mode):
        rect = backend.rectangle(target)
        state = backend.observe(target, options['include_text'], options['max_elements'], cancel)
        image = backend.capture(target, cancel, mode) if options['include_screenshot'] else None
        raise_if_cancel_requested(cancel)
        current = backend.resolve(target)
        if rect != backend.rectangle(current):
            raise ComputerUseError('Window changed during observation; observe again.')
        token = uuid.uuid4().hex
        view = {'window': current, 'observation_id': token,
                'screenshotId': token if image is not None else None,
                'bounds': dict(zip(('left', 'top', 'right', 'bottom'), rect)),
                'coordinate_space': 'window_pixels', 'accessibility': state.get('accessibility'),
                'native_focus': state.get('native_focus'), 'expires_in_seconds': ttl,
                'capture_scope': 'selected_window_only' if mode == 'window' else 'visible_screen_region'}
        if image is not None:
            if image.size != (rect[2] - rect[0], rect[3] - rect[1]):
                raise ComputerUseError(f'Capture size {image.size} does not match window bounds; observe again.')
            overlay = None
            if pointer_feedback is not None:
                image, overlay = annotate_action(image, rect, pointer_feedback)
            stream = io.BytesIO()
            image.save(stream, format='PNG', compress_level=1)
            view.update(width=image.width, height=image.height, mime_type='image/png')
            screenshots.append({key: view[key] for key in (
                'window', 'observation_id', 'screenshotId', 'bounds', 'coordinate_space',
                'capture_scope', 'width', 'height', 'mime_type')})
            screenshots[-1].update({'id': token, 'image_order': len(screenshots) - 1,
                                'z_index': state.get('z_order', {}).get(target['id']),
                                'base64_image': base64.b64encode(stream.getvalue()).decode('ascii')})
            if overlay is not None:
                screenshots[-1]['action_overlay'] = overlay
        observations[token] = Observation(
            owner, current, rect, state.get('elements', []), state.get('focus'),
            clock(), generation, image is not None, state.get('native_focus'), window, options.copy())
        return view, state

    primary, state = capture(window, options['capture_mode'])
    related = state.get('related_windows', [])
    # The backend reports native owner/thread relations; never infer popups from titles.
    transients = state.get('transient_windows', []) if options['include_related'] else []
    selected = transients[:MAX_SCREENSHOTS - 1]
    related_states = []
    for target in selected:
        raise_if_cancel_requested(cancel)
        mode = 'visible_region' if target.get('is_tool_window') else options['capture_mode']
        try:
            view, _ = capture(target, mode)
            related_states.append(view)
        except ComputerUseError as exc:
            related_states.append({'window': target, 'observation_error': str(exc)})
    # Do not publish credentials if a captured window moved/closed while others were captured.
    for observation in observations.values():
        current = backend.resolve(observation.window)
        if backend.rectangle(current) != observation.rect:
            raise ComputerUseError('A captured window changed during the snapshot; observe again.')
    result = {**primary, 'kind': 'computer_use_state', 'screenshots': screenshots,
              'related_windows': related, 'related_states': related_states,
              'omitted_window_ids': [w['id'] for w in transients[len(selected):]],
              'settle_ms': options['settle_ms'], 'render_complete_verified': False,
              'next': 'Inspect the returned images/state before choosing one action. Use that window\'s observation_id and window-relative coordinates. A new get_window_state is needed only if the snapshot is insufficient or stale.'}
    return result, observations
