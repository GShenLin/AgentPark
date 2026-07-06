from __future__ import annotations

import threading
import time


class NodeLiveOutputStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._items: dict[tuple[str, str], dict] = {}
        self._versions: dict[tuple[str, str], int] = {}

    @staticmethod
    def _key(graph_id: str, node_id: str) -> tuple[str, str]:
        return (str(graph_id or "default").strip() or "default", str(node_id or "").strip())

    def update(self, graph_id: str, node_id: str, text: str, *, trace_id: str = "") -> None:
        key = self._key(graph_id, node_id)
        if not key[1]:
            return
        now = time.time()
        with self._condition:
            version = int(self._versions.get(key) or 0) + 1
            self._versions[key] = version
            current = self._items.get(key) if isinstance(self._items.get(key), dict) else {}
            self._items[key] = {
                "text": str(text or ""),
                "thinking_text": str((current or {}).get("thinking_text") or ""),
                "trace_id": str(trace_id or ""),
                "updated_at": now,
                "is_streaming": True,
                "version": version,
                # Persist interactive_session_id across text updates so it is
                # not erased before the SSE client can observe stdin_ready.
                "interactive_session_id": str((current or {}).get("interactive_session_id") or ""),
            }
            self._condition.notify_all()

    def update_thinking(self, graph_id: str, node_id: str, text: str, *, trace_id: str = "", event: dict | None = None) -> None:
        key = self._key(graph_id, node_id)
        if not key[1]:
            return
        now = time.time()
        with self._condition:
            version = int(self._versions.get(key) or 0) + 1
            self._versions[key] = version
            current = self._items.get(key) if isinstance(self._items.get(key), dict) else {}
            self._items[key] = {
                "text": str((current or {}).get("text") or ""),
                "thinking_text": str(text or ""),
                "trace_id": str(trace_id or (current or {}).get("trace_id") or ""),
                "updated_at": now,
                "is_streaming": True,
                "version": version,
                "event_type": "node_thinking_delta",
                "event": dict(event or {"type": "node_thinking_delta", "text": str(text or "")}),
                "interactive_session_id": str((current or {}).get("interactive_session_id") or ""),
            }
            self._condition.notify_all()

    def publish_event(
        self,
        graph_id: str,
        node_id: str,
        event_type: str,
        event: dict | None = None,
        *,
        trace_id: str = "",
    ) -> None:
        key = self._key(graph_id, node_id)
        if not key[1]:
            return
        now = time.time()
        with self._condition:
            version = int(self._versions.get(key) or 0) + 1
            current = self._items.get(key) if isinstance(self._items.get(key), dict) else {}
            self._versions[key] = version
            event_type_lower = str(event_type or "").strip().lower()
            # Persist the session_id when stdin_ready fires; clear it on stdin_closed
            # or node_message_done. This avoids a race where a subsequent update()
            # overwrites the transient event before the SSE client sees it.
            if event_type_lower == "stdin_ready":
                persistent_session = str((event or {}).get("session_id") or "")
            elif event_type_lower in {"stdin_closed", "node_message_done"}:
                persistent_session = ""
            else:
                persistent_session = str((current or {}).get("interactive_session_id") or "")
            self._items[key] = {
                "text": str((current or {}).get("text") or ""),
                "thinking_text": str((current or {}).get("thinking_text") or ""),
                "trace_id": str(trace_id or (current or {}).get("trace_id") or ""),
                "updated_at": now,
                "is_streaming": bool((current or {}).get("is_streaming")),
                "version": version,
                "event_type": str(event_type or "").strip(),
                "event": dict(event or {}),
                "interactive_session_id": persistent_session,
            }
            self._condition.notify_all()

    def publish_completion_event(
        self,
        graph_id: str,
        node_id: str,
        event_type: str,
        event: dict | None = None,
        *,
        trace_id: str = "",
    ) -> None:
        key = self._key(graph_id, node_id)
        if not key[1]:
            return
        now = time.time()
        with self._condition:
            version = int(self._versions.get(key) or 0) + 1
            current = self._items.get(key) if isinstance(self._items.get(key), dict) else {}
            self._versions[key] = version
            self._items[key] = {
                "text": "",
                "thinking_text": "",
                "trace_id": str(trace_id or (current or {}).get("trace_id") or ""),
                "updated_at": now,
                "is_streaming": False,
                "version": version,
                "event_type": str(event_type or "").strip(),
                "event": dict(event or {}),
                "interactive_session_id": "",
            }
            self._condition.notify_all()

    def clear(self, graph_id: str, node_id: str) -> None:
        key = self._key(graph_id, node_id)
        with self._condition:
            if key not in self._items:
                return
            version = int(self._versions.get(key) or 0) + 1
            self._versions[key] = version
            self._items.pop(key, None)
            self._condition.notify_all()

    def get(self, graph_id: str, node_id: str) -> dict:
        key = self._key(graph_id, node_id)
        with self._lock:
            item = self._items.get(key)
            if isinstance(item, dict):
                return dict(item)
            version = int(self._versions.get(key) or 0)
            return {"version": version} if version > 0 else {}

    def wait_for_change(self, graph_id: str, node_id: str, last_version: int, timeout: float = 15.0) -> dict:
        key = self._key(graph_id, node_id)
        deadline = time.monotonic() + max(0.1, float(timeout or 0.1))
        with self._condition:
            while int(self._versions.get(key) or 0) <= int(last_version or 0):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)
            item = self._items.get(key)
            version = int(self._versions.get(key) or 0)
            if isinstance(item, dict):
                return dict(item)
            return {"version": version, "text": "", "is_streaming": False}
