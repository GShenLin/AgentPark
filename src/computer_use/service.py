from __future__ import annotations

import base64
import io
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import contextmanager, nullcontext

from src.runtime_cancellation import raise_if_cancel_requested
from .contracts import ComputerUseError, Observation, integer


class ComputerUseService:
    """Serialize desktop access and bind every input to a recent owned observation."""

    def __init__(self, backend, *, clock=time.monotonic, observation_ttl=60, capacity=64):
        self.backend = backend
        self.clock = clock
        self.ttl = observation_ttl
        self.capacity = capacity
        self.lock = threading.Lock()
        self.observations = OrderedDict()
        self.generation = 0
        self.shared = getattr(backend, 'desktop_session', None)

    @contextmanager
    def access(self, cancel):
        while not self.lock.acquire(timeout=0.05):
            raise_if_cancel_requested(cancel)
        try:
            raise_if_cancel_requested(cancel)
            with self.shared.access(cancel) if self.shared else nullcontext():
                yield
        finally:
            self.lock.release()

    def call(self, method, owner, args, cancel=None):
        with self.access(cancel):
            if method == 'list_windows':
                return {'windows': self.backend.list_windows()}
            if method == 'list_apps':
                return {'apps': self.backend.list_apps()}
            if method == 'launch_app':
                app = args['app']
                if not isinstance(app, str) or not app:
                    raise ComputerUseError('app must be a nonempty app identifier')
                self._invalidate()
                self.backend.launch(app)
                raise_if_cancel_requested(cancel)
                return {'launched': app, 'next': 'Call list_windows to select the resulting window.'}
            if method == 'get_window':
                candidates = [w for w in self.backend.list_windows() if w['id'] == integer(args['id'], 'id', 1)]
                if args.get('app'):
                    candidates = [w for w in candidates if w['app'] == args['app']]
                if len(candidates) != 1:
                    raise ComputerUseError('Window is unavailable; call list_windows again.')
                return {'window': candidates[0]}
            window = self.backend.resolve(args['window'])
            if method == 'get_window_state':
                return self._observe(owner, window, args, cancel)
            if method == 'activate_window':
                self._invalidate()
                self.backend.activate(window)
                return {'window': window, 'observation_invalidated': True, 'next': 'Call get_window_state.'}
            observation = self._observation(owner, window, args)
            if self.backend.rectangle(window) != observation.rect:
                raise ComputerUseError('Window moved or resized; call get_window_state again.')
            # Invalidate before input: a failed/partially cancelled action is never replayable.
            self._invalidate()
            self.backend.act(method, window, observation, args, cancel)
            raise_if_cancel_requested(cancel)
            return {'window': self.backend.resolve(window), 'action': method,
                    'observation_invalidated': True, 'next': 'Call get_window_state to verify the result.'}

    def _observe(self, owner, window, args, cancel):
        # A failed refresh must not leave a previous view usable for later input.
        for token, item in list(self.observations.items()):
            if item.owner == owner:
                del self.observations[token]
        include_text = args.get('include_text', False)
        include_image = args.get('include_screenshot', True)
        if not isinstance(include_text, bool) or not isinstance(include_image, bool):
            raise ComputerUseError('include_text and include_screenshot must be booleans')
        if not include_text and not include_image:
            raise ComputerUseError('Request a screenshot, accessibility text, or both.')
        limit = integer(args.get('max_elements', 200), 'max_elements', 1, 500)
        rect = self.backend.rectangle(window)
        state = self.backend.observe(window, include_text, limit, cancel)
        result = {'window': window, 'accessibility': state.get('accessibility'),
                  'coordinate_space': 'window_pixels', 'bounds': dict(zip(('left', 'top', 'right', 'bottom'), rect))}
        image = self.backend.capture(window, cancel) if include_image else None
        raise_if_cancel_requested(cancel)
        if rect != self.backend.rectangle(window):
            raise ComputerUseError('Window changed during observation; observe again.')
        if image is not None:
            # WGC includes the visible frame, whose origin is returned by rectangle().
            if image.size != (rect[2] - rect[0], rect[3] - rect[1]):
                raise ComputerUseError(f'Capture size {image.size} does not match window bounds; observe again.')
            stream = io.BytesIO()
            image.save(stream, format='PNG', compress_level=1)
            result.update(base64_image=base64.b64encode(stream.getvalue()).decode('ascii'),
                          mime_type='image/png', width=image.width, height=image.height)
        now = self.clock()
        for token, item in list(self.observations.items()):
            if item.owner == owner or now - item.created > self.ttl:
                del self.observations[token]
        token = uuid.uuid4().hex
        self.observations[token] = Observation(owner, window, rect, state.get('elements', []),
                                                state.get('focus'), now, self._generation(), include_image)
        while len(self.observations) > self.capacity:
            self.observations.popitem(last=False)
        result.update(observation_id=token, screenshotId=token if include_image else None, expires_in_seconds=self.ttl)
        return result

    def _observation(self, owner, window, args):
        token = args.get('observation_id') or args.get('screenshotId')
        observation = self.observations.get(token)
        if (observation is None or observation.owner != owner or
                observation.generation != self._generation() or self.clock() - observation.created > self.ttl):
            raise ComputerUseError('Observation is missing, expired, or already consumed; call get_window_state.')
        for field in ('id', 'app', 'pid', 'process_started'):
            if observation.window[field] != window[field]:
                raise ComputerUseError('Observation belongs to another window or process.')
        if args.get('screenshotId') and args['screenshotId'] != token:
            raise ComputerUseError('screenshotId must match observation_id.')
        if args.get('element_index') is None and any(args.get(k) is not None for k in ('x', 'y', 'from_x', 'to_x')):
            if not observation.has_image:
                raise ComputerUseError('Coordinate input requires a screenshot observation.')
        return observation

    def _invalidate(self):
        self.generation += 1
        if self.shared:
            self.shared.bump()
        self.observations.clear()

    def _generation(self):
        return self.shared.epoch() if self.shared else self.generation
