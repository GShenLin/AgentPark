from __future__ import annotations

import threading
import time
from typing import Callable


class CompanionInboxWatcher:
    def __init__(self, drain: Callable[[], None], *, interval_seconds: float = 0.5) -> None:
        self.drain = drain
        self.interval_seconds = max(0.1, float(interval_seconds))
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        if self.thread is not None:
            return
        thread = threading.Thread(target=self._run, name="companion-inbox-watcher", daemon=True)
        self.thread = thread
        thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        thread = self.thread
        if thread is not None:
            thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval_seconds):
            try:
                self.drain()
            except Exception:
                continue
