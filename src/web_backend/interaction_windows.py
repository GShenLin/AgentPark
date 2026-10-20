"""Deliver user-input widgets from backend events, independently of browser presence."""
from __future__ import annotations

import json
import logging
import queue
import re
import threading
from collections import deque
from collections.abc import Callable

from src.user_interaction_store import read_interaction_request, set_interaction_delivery
from .graph_event_stream import GraphEventStreamStore

logger = logging.getLogger(__name__)


class InteractionWindows:
    def __init__(self, events: GraphEventStreamStore, launch: Callable[[str, int], dict]):
        self.events, self.launch = events, launch
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._lock = threading.Lock()
        self._seen: deque[str] = deque(maxlen=4096)
        self._thread: threading.Thread | None = None
        self._unsubscribe: Callable[[], None] | None = None
        self._closed = False

    def start(self, port: int) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("Invalid interaction window listener port")
        if self._thread or self._closed:
            raise RuntimeError("Interaction window service cannot be started twice")
        self._thread = threading.Thread(target=self._run, args=(port,), name="interaction-windows", daemon=True)
        self._thread.start()
        self._unsubscribe = self.events.subscribe(self._receive)

    def close(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
        with self._lock:
            self._closed = True
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=30)
            if self._thread.is_alive():
                raise RuntimeError("Interaction window service did not stop")

    def _receive(self, event: dict) -> None:
        if (event.get("event") != "runtime_notice" or event.get("source") != "user_interaction"
                or event.get("stage") != "user_interaction_created" or event.get("stream_snapshot") is True):
            return
        try:
            payload = json.loads(event["message"])
            request_id = payload["request_id"]
            if not isinstance(request_id, str) or not re.fullmatch(r"[a-f0-9]{32}", request_id):
                raise ValueError("Invalid interaction window request id")
        except (ValueError, TypeError, KeyError):
            logger.exception("Invalid interaction creation event")
            return
        with self._lock:
            if self._closed or request_id in self._seen:
                return
            self._seen.append(request_id)
            self._queue.put(request_id)

    def _run(self, port: int) -> None:
        while (request_id := self._queue.get()) is not None:
            if self._closed:
                continue
            try:
                request = read_interaction_request(request_id)
                if request["status"] != "pending":
                    continue
                self._deliver(request, port)
            except Exception:
                logger.exception("Interaction widget delivery failed for %s", request_id)

    def _deliver(self, request: dict, port: int) -> None:
        request_id = request["id"]
        set_interaction_delivery(request_id, "opening")
        try:
            self.launch(request_id, port)
        except Exception as exc:
            error = str(getattr(exc, "detail", None) or exc)
            logger.exception("Could not open interaction widget %s", request_id)
            set_interaction_delivery(request_id, "failed", error)
        else:
            set_interaction_delivery(request_id, "opened")
        self.events.publish(request["agent"]["graph_id"], {
            "event": "user_interaction_delivery", "request_id": request_id,
            "node_instance_id": request["agent"]["node_id"],
        })
