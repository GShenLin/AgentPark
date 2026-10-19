"""Backend-owned completion delivery; browser connections only report foreground presence."""
from __future__ import annotations

import logging
import queue
import threading
from collections import deque
from collections.abc import Callable

from .graph_event_stream import GraphEventStreamStore

logger = logging.getLogger(__name__)


class NodeWindowAlerts:
    def __init__(self, events: GraphEventStreamStore, launch: Callable[[str, str, int], dict]):
        self.events = events
        self.launch = launch
        self._lock = threading.Lock()
        self._focused: set[str] = set()
        self._seen: set[str] = set()
        self._receipts: deque[str] = deque()
        self._queue: queue.Queue[dict | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._port: int | None = None
        self._last_delivery: dict | None = None
        self._closed = False

    def start(self, port: int) -> None:
        if not 1 <= port <= 65535:
            raise ValueError('Invalid desktop notification listener port')
        with self._lock:
            if self._thread is not None or self._closed:
                raise RuntimeError('Desktop notification service cannot be started twice')
            self._port = port
            self._thread = threading.Thread(target=self._run, name='node-window-alerts', daemon=True)
            self._thread.start()
            self._unsubscribe = self.events.subscribe(self._receive)

    def close(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
        with self._lock:
            self._closed = True
            self._focused.clear()
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=30)
            if self._thread.is_alive():
                raise RuntimeError('Desktop notification service did not stop')

    def set_focused(self, connection_id: str, focused: bool) -> None:
        with self._lock:
            if focused and not self._closed:
                self._focused.add(connection_id)
            else:
                self._focused.discard(connection_id)

    def status(self) -> dict:
        with self._lock:
            return {
                'running': bool(self._thread and self._thread.is_alive() and not self._closed),
                'port': self._port, 'focused_pages': len(self._focused),
                'last_delivery': dict(self._last_delivery) if self._last_delivery else None,
            }

    def _receive(self, event: dict) -> None:
        if event.get('event') != 'work_persisted_alert' or event.get('stream_snapshot') is True:
            return
        for field in ('alert_id', 'graph_id', 'node_instance_id'):
            if not isinstance(event.get(field), str) or not event[field].strip():
                logger.error('Invalid persisted-work event: missing %s', field)
                return
        with self._lock:
            if self._closed or event['alert_id'] in self._seen:
                return
            self._seen.add(event['alert_id'])
            self._receipts.append(event['alert_id'])
            if len(self._receipts) > 4096:
                self._seen.remove(self._receipts.popleft())
            if self._focused:
                self._record(event, 'foreground')
                return
            self._queue.put(event)

    def _record(self, event: dict, outcome: str, error: str = '') -> None:
        self._last_delivery = {
            'alert_id': event['alert_id'], 'graph_id': event['graph_id'],
            'node_id': event['node_instance_id'], 'outcome': outcome, 'error': error,
        }

    def _run(self) -> None:
        while (event := self._queue.get()) is not None:
            with self._lock:
                if self._closed:
                    continue
                if self._focused:
                    self._record(event, 'foreground')
                    continue
            try:
                self.launch(event['node_instance_id'], event['graph_id'], self._port)
            except Exception as exc:
                error = str(getattr(exc, 'detail', None) or exc)
                logger.exception('Node window alert failed: %s', event['alert_id'])
                with self._lock:
                    self._record(event, 'failed', error)
                self.events.publish(event['graph_id'], {
                    'event': 'node_window_alert_failed', 'alert_id': event['alert_id'],
                    'node_instance_id': event['node_instance_id'], 'message': error,
                })
            else:
                with self._lock:
                    self._record(event, 'opened')
