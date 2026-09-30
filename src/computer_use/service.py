from __future__ import annotations

import threading
import time
from dataclasses import asdict
from collections import OrderedDict
from contextlib import contextmanager, nullcontext

from src.runtime_cancellation import CancellationRequested, raise_if_cancel_requested
from .contracts import ComputerUseError, integer
from .observations import collect_observations, observation_options


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
                return self._refresh_after_action(owner, window, window, method, {}, cancel)
            observation = self._observation(owner, window, args)
            if self.backend.rectangle(window) != observation.rect:
                raise ComputerUseError('Window moved or resized; call get_window_state again.')
            # Invalidate before input: a failed/partially cancelled action is never replayable.
            self._invalidate()
            pointer_feedback = self.backend.act(method, window, observation, args, cancel)
            raise_if_cancel_requested(cancel)
            return self._refresh_after_action(owner, window, observation.refresh_window,
                                              method, observation.options, cancel, pointer_feedback)

    def _refresh_after_action(self, owner, target, refresh_window, method, options, cancel, pointer_feedback=None):
        receipt = {'input_window': target, 'action': method, 'input_dispatched': True,
                   'result_verified': False, 'previous_observation_consumed': True}
        if pointer_feedback is not None:
            receipt['dispatched_pointer_points'] = [asdict(point) for point in pointer_feedback.points]
        try:
            window = self.backend.resolve(refresh_window)
            state = self._observe(owner, window, options, cancel, pointer_feedback)
        except CancellationRequested:
            raise
        except Exception as exc:
            return {**receipt, 'status': 'error', 'phase': 'post_action_observation',
                    'error': f'{type(exc).__name__}: {exc}', 'observation_available': False,
                    'next': 'Input was already sent. Do not repeat it blindly. Reacquire the remaining window and observe to determine the outcome.'}
        return {**state, **receipt, 'observation_available': True}

    def _observe(self, owner, window, args, cancel, pointer_feedback=None):
        # A failed refresh must not leave a previous view usable for later input.
        for token, item in list(self.observations.items()):
            if item.owner == owner:
                del self.observations[token]
        options = observation_options(args)
        result, observations = collect_observations(
            self.backend, owner, window, options, cancel, clock=self.clock,
            generation=self._generation(), ttl=self.ttl, pointer_feedback=pointer_feedback)
        now = self.clock()
        for token, item in list(self.observations.items()):
            if item.owner == owner or now - item.created > self.ttl:
                del self.observations[token]
        self.observations.update(observations)
        while len(self.observations) > self.capacity:
            self.observations.popitem(last=False)
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
