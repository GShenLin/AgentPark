from __future__ import annotations

import threading
import time
from collections.abc import Callable


MAX_LIVE_ACTIVITY_BLOCKS = 64
MAX_LIVE_EVENT_STRING_CHARS = 4096
MAX_LIVE_EVENT_LIST_ITEMS = 64
MAX_LIVE_EVENT_DICT_FIELDS = 64
MAX_LIVE_EVENT_DEPTH = 4
MAX_LIVE_MEDIA_CHUNKS = 96


def live_output_requires_snapshot(item: object, last_delivered_version: int) -> bool:
    """Return whether a consumer must receive the full live-output snapshot.

    The store intentionally keeps only its latest state. A producer can therefore
    advance through multiple versions before an SSE consumer wakes up. A delta is
    safe only when it is based on the exact version that consumer last received.
    """
    if not isinstance(item, dict):
        return True
    current_version = int(item.get("version") or 0)
    expected_version = int(last_delivered_version or 0) + 1
    return bool(item.get("snapshot_required")) or current_version != expected_version


def build_live_output_payload(
    graph_id: str,
    node_id: str,
    item: dict | None,
    *,
    snapshot: bool = False,
    last_delivered_version: int = 0,
) -> dict:
    current = item if isinstance(item, dict) else {}
    send_snapshot = snapshot or live_output_requires_snapshot(current, last_delivered_version)
    payload = {
        "node_id": str(node_id or "").strip(),
        "graph_id": str(graph_id or "default").strip() or "default",
        "stream_type": "snapshot" if send_snapshot else "delta",
        "base_version": int(current.get("version") or 0) if send_snapshot else int(last_delivered_version or 0),
        "live_message": str(current.get("text") or "") if send_snapshot else "",
        "thinking_message": str(current.get("thinking_text") or "") if send_snapshot else "",
        "live_delta": "" if send_snapshot else str(current.get("live_delta") or ""),
        "thinking_delta": "" if send_snapshot else str(current.get("thinking_delta") or ""),
        "version": int(current.get("version") or 0),
        "trace_id": str(current.get("trace_id") or ""),
        "updated_at": float(current.get("updated_at") or 0),
        "is_streaming": bool(current.get("is_streaming")),
        "event_type": str(current.get("event_type") or ""),
        "event": current.get("event") if isinstance(current.get("event"), dict) else None,
        "interactive_session_id": str(current.get("interactive_session_id") or ""),
        "media_chunks": NodeLiveOutputStore._copy_media_chunks(current),
    }
    if send_snapshot or bool(current.get("activity_blocks_changed")):
        payload["activity_blocks"] = NodeLiveOutputStore._copy_activity_blocks(current)
    return payload


def _compact_live_value(value: object, *, depth: int = 0) -> object:
    if depth >= MAX_LIVE_EVENT_DEPTH:
        return "[nested value omitted]"
    if isinstance(value, str):
        if len(value) <= MAX_LIVE_EVENT_STRING_CHARS:
            return value
        return value[:MAX_LIVE_EVENT_STRING_CHARS] + "…"
    if isinstance(value, dict):
        output: dict[str, object] = {}
        for index, (key, child) in enumerate(value.items()):
            if index >= MAX_LIVE_EVENT_DICT_FIELDS:
                output["_truncated_fields"] = len(value) - MAX_LIVE_EVENT_DICT_FIELDS
                break
            output[str(key)] = _compact_live_value(child, depth=depth + 1)
        return output
    if isinstance(value, (list, tuple)):
        output = [
            _compact_live_value(child, depth=depth + 1)
            for child in list(value)[:MAX_LIVE_EVENT_LIST_ITEMS]
        ]
        if len(value) > MAX_LIVE_EVENT_LIST_ITEMS:
            output.append({"_truncated_items": len(value) - MAX_LIVE_EVENT_LIST_ITEMS})
        return output
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _compact_live_value(str(value), depth=depth)


def _compact_live_event(event: dict | None) -> dict:
    compacted = _compact_live_value(event or {})
    return compacted if isinstance(compacted, dict) else {}


class NodeLiveOutputStore:
    def __init__(self, on_change: Callable[[str, str, dict], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._items: dict[tuple[str, str], dict] = {}
        self._versions: dict[tuple[str, str], int] = {}
        self._on_change = on_change

    @staticmethod
    def _key(graph_id: str, node_id: str) -> tuple[str, str]:
        return (str(graph_id or "default").strip() or "default", str(node_id or "").strip())

    def update(
        self,
        graph_id: str,
        node_id: str,
        text: str,
        *,
        trace_id: str = "",
        delta: str = "",
    ) -> None:
        key = self._key(graph_id, node_id)
        if not key[1]:
            return
        now = time.time()
        with self._condition:
            version = int(self._versions.get(key) or 0) + 1
            self._versions[key] = version
            current = self._items.get(key) if isinstance(self._items.get(key), dict) else {}
            previous = str((current or {}).get("text") or "")
            next_text = str(text or "")
            next_delta = str(delta or "")
            snapshot_required = not (
                len(next_text) == len(previous) + len(next_delta)
                and next_text.startswith(previous)
                and next_text.endswith(next_delta)
            )
            self._items[key] = {
                "text": next_text,
                "thinking_text": str((current or {}).get("thinking_text") or ""),
                "live_delta": "" if snapshot_required else next_delta,
                "thinking_delta": "",
                "snapshot_required": snapshot_required,
                "activity_blocks": self._copy_activity_blocks(current),
                "activity_blocks_changed": False,
                "media_chunks": self._copy_media_chunks(current),
                "trace_id": str(trace_id or ""),
                "updated_at": now,
                "is_streaming": True,
                "version": version,
                # Persist interactive_session_id across text updates so it is
                # not erased before the SSE client can observe stdin_ready.
                "interactive_session_id": str((current or {}).get("interactive_session_id") or ""),
            }
            self._condition.notify_all()
        self._notify_change(key)

    def update_thinking(
        self,
        graph_id: str,
        node_id: str,
        text: str,
        *,
        trace_id: str = "",
        event: dict | None = None,
        delta: str = "",
    ) -> None:
        key = self._key(graph_id, node_id)
        if not key[1]:
            return
        now = time.time()
        with self._condition:
            version = int(self._versions.get(key) or 0) + 1
            self._versions[key] = version
            current = self._items.get(key) if isinstance(self._items.get(key), dict) else {}
            previous = str((current or {}).get("thinking_text") or "")
            next_text = str(text or "")
            next_delta = str(delta or "")
            snapshot_required = not (
                len(next_text) == len(previous) + len(next_delta)
                and next_text.startswith(previous)
                and next_text.endswith(next_delta)
            )
            self._items[key] = {
                "text": str((current or {}).get("text") or ""),
                "thinking_text": next_text,
                "live_delta": "",
                "thinking_delta": "" if snapshot_required else next_delta,
                "snapshot_required": snapshot_required,
                "activity_blocks": self._copy_activity_blocks(current),
                "activity_blocks_changed": False,
                "media_chunks": self._copy_media_chunks(current),
                "trace_id": str(trace_id or (current or {}).get("trace_id") or ""),
                "updated_at": now,
                "is_streaming": True,
                "version": version,
                "event_type": "node_thinking_delta",
                "event": _compact_live_event(
                    {
                        "type": str((event or {}).get("type") or "node_thinking_delta"),
                        "delta": next_delta,
                    }
                ),
                "interactive_session_id": str((current or {}).get("interactive_session_id") or ""),
            }
            self._condition.notify_all()
        self._notify_change(key)

    @staticmethod
    def _copy_activity_blocks(item: object) -> list[dict]:
        if not isinstance(item, dict):
            return []
        blocks = item.get("activity_blocks")
        return [dict(block) for block in blocks if isinstance(block, dict)] if isinstance(blocks, list) else []

    @staticmethod
    def _copy_media_chunks(item: object) -> list[dict]:
        if not isinstance(item, dict):
            return []
        chunks = item.get("media_chunks")
        return [dict(chunk) for chunk in chunks if isinstance(chunk, dict)] if isinstance(chunks, list) else []

    def update_activity(
        self,
        graph_id: str,
        node_id: str,
        block: dict,
        *,
        trace_id: str = "",
        event: dict | None = None,
    ) -> None:
        key = self._key(graph_id, node_id)
        if not key[1] or not isinstance(block, dict):
            return
        block_id = str(block.get("id") or "").strip()
        block_type = str(block.get("type") or "").strip().lower()
        if not block_id or not block_type:
            raise ValueError("live activity block requires id and type")
        now = time.time()
        with self._condition:
            version = int(self._versions.get(key) or 0) + 1
            self._versions[key] = version
            current = self._items.get(key) if isinstance(self._items.get(key), dict) else {}
            blocks = self._copy_activity_blocks(current)
            next_block = _compact_live_event(block)
            replaced = False
            for index, existing in enumerate(blocks):
                if str(existing.get("id") or "").strip() == block_id:
                    merged_block = {**existing, **next_block}
                    for field in ("action", "details"):
                        existing_value = existing.get(field)
                        next_value = next_block.get(field)
                        if isinstance(existing_value, dict) and isinstance(next_value, dict):
                            merged_block[field] = {**existing_value, **next_value}
                    blocks[index] = merged_block
                    replaced = True
                    break
            if not replaced:
                blocks.append(next_block)
            blocks = blocks[-MAX_LIVE_ACTIVITY_BLOCKS:]
            self._items[key] = {
                "text": str((current or {}).get("text") or ""),
                "thinking_text": str((current or {}).get("thinking_text") or ""),
                "live_delta": "",
                "thinking_delta": "",
                "snapshot_required": False,
                "activity_blocks": blocks,
                "activity_blocks_changed": True,
                "media_chunks": self._copy_media_chunks(current),
                "trace_id": str(trace_id or (current or {}).get("trace_id") or ""),
                "updated_at": now,
                "is_streaming": True,
                "version": version,
                "event_type": str((event or {}).get("type") or "live_activity"),
                "event": _compact_live_event(event),
                "interactive_session_id": str((current or {}).get("interactive_session_id") or ""),
            }
            self._condition.notify_all()
        self._notify_change(key)

    def remove_activity(
        self,
        graph_id: str,
        node_id: str,
        block_id: str,
        *,
        trace_id: str = "",
        event: dict | None = None,
    ) -> None:
        key = self._key(graph_id, node_id)
        normalized_block_id = str(block_id or "").strip()
        if not key[1] or not normalized_block_id:
            return
        now = time.time()
        with self._condition:
            current = self._items.get(key) if isinstance(self._items.get(key), dict) else {}
            blocks = self._copy_activity_blocks(current)
            remaining = [
                block
                for block in blocks
                if str(block.get("id") or "").strip() != normalized_block_id
            ]
            if len(remaining) == len(blocks):
                return
            version = int(self._versions.get(key) or 0) + 1
            self._versions[key] = version
            self._items[key] = {
                "text": str((current or {}).get("text") or ""),
                "thinking_text": str((current or {}).get("thinking_text") or ""),
                "live_delta": "",
                "thinking_delta": "",
                "snapshot_required": False,
                "activity_blocks": remaining,
                "activity_blocks_changed": True,
                "media_chunks": self._copy_media_chunks(current),
                "trace_id": str(trace_id or (current or {}).get("trace_id") or ""),
                "updated_at": now,
                "is_streaming": True,
                "version": version,
                "event_type": str((event or {}).get("type") or "live_activity_removed"),
                "event": _compact_live_event(event),
                "interactive_session_id": str((current or {}).get("interactive_session_id") or ""),
            }
            self._condition.notify_all()
        self._notify_change(key)

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
            media_chunks = self._copy_media_chunks(current)
            compact_event = _compact_live_event(event)
            if event_type_lower == "audio_stream_start":
                media_chunks = [compact_event]
            elif event_type_lower in {"audio_stream_chunk", "audio_stream_end"}:
                starts = [item for item in media_chunks if str(item.get("type") or "").lower() == "audio_stream_start"][-1:]
                tail = [item for item in media_chunks if str(item.get("type") or "").lower() != "audio_stream_start"]
                media_chunks = [*starts, *tail[-(MAX_LIVE_MEDIA_CHUNKS - 2):], compact_event]
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
                "live_delta": "",
                "thinking_delta": "",
                "snapshot_required": False,
                "activity_blocks": self._copy_activity_blocks(current),
                "activity_blocks_changed": False,
                "media_chunks": media_chunks,
                "trace_id": str(trace_id or (current or {}).get("trace_id") or ""),
                "updated_at": now,
                "is_streaming": bool((current or {}).get("is_streaming")),
                "version": version,
                "event_type": str(event_type or "").strip(),
                "event": compact_event,
                "interactive_session_id": persistent_session,
            }
            self._condition.notify_all()
        self._notify_change(key)

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
                "live_delta": "",
                "thinking_delta": "",
                "snapshot_required": False,
                "activity_blocks": [],
                "activity_blocks_changed": True,
                "media_chunks": self._copy_media_chunks(current),
                "trace_id": str(trace_id or (current or {}).get("trace_id") or ""),
                "updated_at": now,
                "is_streaming": False,
                "version": version,
                "event_type": str(event_type or "").strip(),
                "event": _compact_live_event(event),
                "interactive_session_id": "",
            }
            self._condition.notify_all()
        self._notify_change(key)

    def clear(self, graph_id: str, node_id: str) -> None:
        key = self._key(graph_id, node_id)
        with self._condition:
            if key not in self._items:
                return
            version = int(self._versions.get(key) or 0) + 1
            self._versions[key] = version
            self._items.pop(key, None)
            self._condition.notify_all()
        self._notify_change(key)

    def _notify_change(self, key: tuple[str, str]) -> None:
        if not callable(self._on_change):
            return
        self._on_change(key[0], key[1], self.get(key[0], key[1]))

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
