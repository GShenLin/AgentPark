from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.file_transaction import append_text, run_with_interprocess_lock


@dataclass
class ContextArtifact:
    artifact_id: str
    graph_id: str
    node_id: str
    event_id: str
    ttl: str
    priority: str
    role: str
    content: str
    consumed: bool = False
    aggregation_key: str = ""


class RuntimeEventContextStore:
    def __init__(self, core: object, metrics: object | None = None, diagnostics: object | None = None) -> None:
        self.core = core
        self.metrics = metrics
        self.diagnostics = diagnostics
        self._artifacts: dict[tuple[str, str], list[ContextArtifact]] = {}
        self._lock = threading.Lock()
        self._audit_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="runtime-event-audit")

    def add_fragment(
        self,
        *,
        graph_id: str,
        node_id: str,
        event_id: str,
        ttl: str,
        priority: str,
        role: str,
        content: str,
        audit_payload: dict[str, Any],
    ) -> None:
        text = str(content or "").strip()
        if not text:
            return
        artifact = ContextArtifact(
            artifact_id=f"{event_id}:{len(text)}:{abs(hash(text))}",
            graph_id=graph_id,
            node_id=node_id,
            event_id=event_id,
            ttl=ttl,
            priority=priority,
            role=role,
            content=text,
        )
        with self._lock:
            self._artifacts.setdefault((graph_id, node_id), []).append(artifact)
        payload = dict(audit_payload)
        payload.update(
            {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                "type": "context_fragment",
                "artifact_id": artifact.artifact_id,
                "graph_id": graph_id,
                "node_id": node_id,
                "event_id": event_id,
                "ttl": ttl,
                "priority": priority,
                "role": role,
                "content_preview": text[:1000],
            }
        )
        self._audit_executor.submit(self._append_audit, graph_id, node_id, payload)

    def upsert_fragment(
        self,
        *,
        graph_id: str,
        node_id: str,
        event_id: str,
        ttl: str,
        priority: str,
        role: str,
        content: str,
        aggregation_key: str,
        audit_payload: dict[str, Any],
    ) -> None:
        text = str(content or "").strip()
        key = str(aggregation_key or "").strip()
        if not text or not key:
            raise ValueError("aggregated context fragments require content and aggregation_key")
        created = False
        with self._lock:
            items = self._artifacts.setdefault((graph_id, node_id), [])
            artifact = next(
                (
                    item
                    for item in items
                    if item.aggregation_key == key and not item.consumed
                ),
                None,
            )
            if artifact is None:
                artifact = ContextArtifact(
                    artifact_id=f"aggregate:{key}",
                    graph_id=graph_id,
                    node_id=node_id,
                    event_id=event_id,
                    ttl=ttl,
                    priority=priority,
                    role=role,
                    content=text,
                    aggregation_key=key,
                )
                items.append(artifact)
                created = True
            else:
                artifact.event_id = event_id
                artifact.ttl = ttl
                artifact.priority = priority
                artifact.role = role
                artifact.content = text
        payload = dict(audit_payload)
        payload.update(
            {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                "type": "context_fragment_aggregate",
                "operation": "create" if created else "update",
                "artifact_id": artifact.artifact_id,
                "aggregation_key": key,
                "graph_id": graph_id,
                "node_id": node_id,
                "event_id": event_id,
                "ttl": ttl,
                "priority": priority,
                "role": role,
                "content_preview": text[:1000],
            }
        )
        self._audit_executor.submit(self._append_audit, graph_id, node_id, payload)

    def consume_for_node(self, graph_id: str, node_id: str, *, include_current_run: bool = True) -> list[dict[str, str]]:
        with self._lock:
            items = list(self._artifacts.get((graph_id, node_id), []))
            remaining: list[ContextArtifact] = []
            output: list[ContextArtifact] = []
            for item in items:
                if item.ttl == "current_run" and not include_current_run:
                    remaining.append(item)
                    continue
                if item.ttl == "persistent":
                    remaining.append(item)
                    output.append(item)
                    continue
                if item.consumed:
                    continue
                item.consumed = True
                output.append(item)
            if remaining:
                self._artifacts[(graph_id, node_id)] = remaining
            else:
                self._artifacts.pop((graph_id, node_id), None)
        priority_order = {"high": 0, "normal": 1, "low": 2}
        output.sort(key=lambda item: priority_order.get(item.priority, 1))
        return [{"role": item.role, "content": item.content} for item in output]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                f"{graph_id}/{node_id}": len(items)
                for (graph_id, node_id), items in self._artifacts.items()
            }

    def _append_audit(self, graph_id: str, node_id: str, payload: dict[str, Any]) -> None:
        try:
            node_dir = self.core.graph_runtime._node_dir(graph_id, node_id)
            path = os.path.join(node_dir, "context_artifacts.jsonl")
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            run_with_interprocess_lock(path + ".lock", lambda: append_text(path, line, encoding="utf-8"))
        except Exception as exc:
            if self.metrics is not None and hasattr(self.metrics, "inc"):
                self.metrics.inc("context_audit_failed")
            if self.diagnostics is not None and hasattr(self.diagnostics, "record"):
                self.diagnostics.record(
                    kind="context_audit_failed",
                    message="failed to append runtime event context audit",
                    error=exc,
                    details={"graph_id": graph_id, "node_id": node_id, "event_id": payload.get("event_id")},
                )
