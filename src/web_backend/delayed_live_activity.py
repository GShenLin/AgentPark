from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable


LiveActivityCallback = Callable[[], None]


@dataclass
class _PendingActivity:
    timer: threading.Timer
    show: LiveActivityCallback
    hide: LiveActivityCallback
    visible: bool = False


class DelayedLiveActivityGate:
    """Expose short-lived activity only after it crosses a visibility threshold."""

    def __init__(self, delay_seconds: float = 1.0) -> None:
        self.delay_seconds = max(0.0, float(delay_seconds))
        self._lock = threading.RLock()
        self._pending: dict[str, _PendingActivity] = {}

    def start(
        self,
        activity_id: str,
        *,
        show: LiveActivityCallback,
        hide: LiveActivityCallback,
    ) -> None:
        normalized_id = str(activity_id or "").strip()
        if not normalized_id:
            raise ValueError("delayed live activity requires an id")

        with self._lock:
            previous = self._pending.pop(normalized_id, None)
            if previous is not None:
                previous.timer.cancel()
                if previous.visible:
                    previous.hide()

            if self.delay_seconds == 0:
                timer = threading.Timer(0, lambda: None)
                self._pending[normalized_id] = _PendingActivity(
                    timer=timer,
                    show=show,
                    hide=hide,
                    visible=True,
                )
                show()
                return

            timer = threading.Timer(self.delay_seconds, self._show, args=(normalized_id,))
            timer.daemon = True
            self._pending[normalized_id] = _PendingActivity(timer=timer, show=show, hide=hide)
            timer.start()

    def finish(
        self,
        activity_id: str,
        *,
        when_visible: LiveActivityCallback | None = None,
    ) -> None:
        normalized_id = str(activity_id or "").strip()
        if not normalized_id:
            return
        with self._lock:
            pending = self._pending.pop(normalized_id, None)
            if pending is None:
                return
            pending.timer.cancel()
            if pending.visible:
                (when_visible or pending.hide)()

    def close(self) -> None:
        with self._lock:
            pending_items = list(self._pending.values())
            self._pending.clear()
            for pending in pending_items:
                pending.timer.cancel()
                if pending.visible:
                    pending.hide()

    def _show(self, activity_id: str) -> None:
        with self._lock:
            pending = self._pending.get(activity_id)
            if pending is None or pending.visible:
                return
            pending.show()
            pending.visible = True
