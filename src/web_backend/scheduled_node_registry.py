import heapq
import math
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ScheduledNodeRegistration:
    graph_id: str
    node_id: str
    config_path: str
    type_id: str
    due_at: float

    @property
    def key(self) -> tuple[str, str]:
        return (self.graph_id, self.node_id)


class ScheduledNodeRegistry:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._entries: dict[tuple[str, str], ScheduledNodeRegistration] = {}
        self._heap: list[tuple[float, int, tuple[str, str]]] = []
        self._sequence = 0

    def rebuild(self, entries: list[ScheduledNodeRegistration]) -> None:
        with self._condition:
            self._entries.clear()
            self._heap.clear()
            for entry in entries:
                self._register_locked(entry)
            self._condition.notify_all()

    def register(self, entry: ScheduledNodeRegistration) -> None:
        with self._condition:
            self._register_locked(entry)
            self._condition.notify_all()

    def unregister(self, graph_id: str, node_id: str) -> None:
        key = (str(graph_id or "").strip(), str(node_id or "").strip())
        with self._condition:
            self._entries.pop(key, None)
            self._condition.notify_all()

    def unregister_graph(self, graph_id: str) -> None:
        target_graph_id = str(graph_id or "").strip()
        with self._condition:
            for key in list(self._entries):
                if key[0] == target_graph_id:
                    self._entries.pop(key, None)
            self._condition.notify_all()

    def snapshot(self) -> list[ScheduledNodeRegistration]:
        with self._condition:
            return list(self._entries.values())

    def wake(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def wait_for_due(self, stop_event: threading.Event) -> list[ScheduledNodeRegistration]:
        with self._condition:
            while not stop_event.is_set():
                self._discard_stale_heap_heads_locked()
                if not self._heap:
                    self._condition.wait(timeout=1.0)
                    continue

                due_at = self._heap[0][0]
                now_ts = time.time()
                wait_seconds = max(0.0, due_at - now_ts)
                if wait_seconds > 0:
                    self._condition.wait(timeout=wait_seconds)
                    continue

                due_entries: list[ScheduledNodeRegistration] = []
                while self._heap:
                    self._discard_stale_heap_heads_locked()
                    if not self._heap or self._heap[0][0] > time.time():
                        break
                    _due_at, _sequence, key = heapq.heappop(self._heap)
                    entry = self._entries.get(key)
                    if entry is None:
                        continue
                    self._entries.pop(key, None)
                    due_entries.append(entry)
                if due_entries:
                    return due_entries
            return []

    def _register_locked(self, entry: ScheduledNodeRegistration) -> None:
        if not math.isfinite(float(entry.due_at)):
            return
        self._sequence += 1
        self._entries[entry.key] = entry
        heapq.heappush(self._heap, (float(entry.due_at), self._sequence, entry.key))

    def _discard_stale_heap_heads_locked(self) -> None:
        while self._heap:
            due_at, _sequence, key = self._heap[0]
            entry = self._entries.get(key)
            if entry is not None and float(entry.due_at) == float(due_at):
                return
            heapq.heappop(self._heap)
