from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .node_tool_history import build_tool_call_history_envelope
from .shared import _append_jsonl_line
from .shared import envelope_text
from .shared import normalize_envelope
from .shared import now_text


@dataclass(frozen=True)
class NodeMemoryPersistenceFailure:
    target: str
    path: str
    error: str


class NodeMemoryPersistenceError(RuntimeError):
    def __init__(self, failures: list[NodeMemoryPersistenceFailure]):
        self.failures = tuple(failures)
        joined = "; ".join(f"{item.target} {item.path}: {item.error}" for item in self.failures)
        super().__init__("Node memory persistence failed: " + joined)


def ensure_node_memory_files(memory_path: str, messages_path: str) -> None:
    failures: list[NodeMemoryPersistenceFailure] = []
    for target, path in (("memory", memory_path), ("messages", messages_path)):
        if not path:
            failures.append(NodeMemoryPersistenceFailure(target=target, path="", error="path is empty"))
            continue
        try:
            if not os.path.exists(path):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "a", encoding="utf-8"):
                    pass
        except Exception as exc:
            failures.append(
                NodeMemoryPersistenceFailure(target=target, path=path, error=f"{type(exc).__name__}: {exc}")
            )
    _raise_if_failures(failures)


def append_node_memory_entry(memory_path: str, messages_path: str, role: str, message: object) -> None:
    envelope = normalize_envelope(message, default_role=role or "assistant")
    payload = envelope_text(envelope)
    if not payload and not (envelope.get("parts") or []):
        return

    failures: list[NodeMemoryPersistenceFailure] = []
    _append_messages_entry(messages_path, role, envelope, failures)
    _append_markdown_entry(memory_path, role, payload, failures)
    _raise_if_failures(failures)


def append_node_tool_call_entry(memory_path: str, messages_path: str, event: dict[str, Any]) -> None:
    if not isinstance(event, dict):
        return
    append_node_memory_entry(memory_path, messages_path, "tool", build_tool_call_history_envelope(event))


def _append_messages_entry(
    messages_path: str,
    role: str,
    envelope: dict[str, Any],
    failures: list[NodeMemoryPersistenceFailure],
) -> None:
    if not messages_path:
        failures.append(NodeMemoryPersistenceFailure(target="messages", path="", error="path is empty"))
        return
    try:
        os.makedirs(os.path.dirname(messages_path), exist_ok=True)
        _append_jsonl_line(
            messages_path,
            {
                "id": str(envelope.get("id") or uuid.uuid4().hex),
                "role": str(role or envelope.get("role") or "assistant"),
                "parts": envelope.get("parts") if isinstance(envelope.get("parts"), list) else [],
                "created_at": str(envelope.get("created_at") or now_text()),
            },
        )
    except Exception as exc:
        failures.append(
            NodeMemoryPersistenceFailure(
                target="messages",
                path=messages_path,
                error=f"{type(exc).__name__}: {exc}",
            )
        )


def _append_markdown_entry(
    memory_path: str,
    role: str,
    payload: str,
    failures: list[NodeMemoryPersistenceFailure],
) -> None:
    if not memory_path:
        failures.append(NodeMemoryPersistenceFailure(target="memory", path="", error="path is empty"))
        return
    try:
        os.makedirs(os.path.dirname(memory_path), exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(memory_path, "a", encoding="utf-8") as handle:
            handle.write(f"\n**[{timestamp}] {str(role or '').strip().lower() or 'assistant'}**: {payload}\n")
    except Exception as exc:
        failures.append(
            NodeMemoryPersistenceFailure(
                target="memory",
                path=memory_path,
                error=f"{type(exc).__name__}: {exc}",
            )
        )


def _raise_if_failures(failures: list[NodeMemoryPersistenceFailure]) -> None:
    if failures:
        raise NodeMemoryPersistenceError(failures)
