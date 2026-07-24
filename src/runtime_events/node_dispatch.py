from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.web_backend.profile_storage import AGENT_PROFILE_DIR, get_profile, profile_category_dir
from src.web_backend.shared import _append_node_pending, build_text_envelope, envelope_preview

from .event_models import CompiledReceiver, CompiledReceiverGroup, RuntimeEventEnvelope


class RuntimeEventNodeDispatch:
    def __init__(self, core: object, metrics: object | None = None, diagnostics: object | None = None) -> None:
        self.core = core
        self.metrics = metrics
        self.diagnostics = diagnostics
        self._executor = ThreadPoolExecutor(thread_name_prefix="runtime-event-dispatch")

    def enqueue(self, *, group: CompiledReceiverGroup, envelope: RuntimeEventEnvelope, profile_id: str) -> None:
        if self.metrics is not None and hasattr(self.metrics, "inc"):
            self.metrics.inc("dispatch_queued", group=group.group_id, event=envelope.event)
        self._executor.submit(self._dispatch, group, envelope, str(profile_id).strip())

    def _dispatch(self, group: CompiledReceiverGroup, envelope: RuntimeEventEnvelope, profile_id: str) -> None:
        try:
            if not profile_id:
                raise ValueError("node.dispatch handler requires an agent profile")
            receiver = self._create_temporary_receiver(group, envelope, profile_id)
            self._enqueue_receiver(receiver, group, envelope, profile_id=profile_id, temporary=True)
            if self.metrics is not None and hasattr(self.metrics, "inc"):
                self.metrics.inc(
                    "dispatch_enqueued",
                    group=group.group_id,
                    event=envelope.event,
                    temporary=True,
                )
        except Exception as exc:
            if self.metrics is not None and hasattr(self.metrics, "inc"):
                self.metrics.inc("dispatch_failed", group=group.group_id, event=envelope.event)
            if self.diagnostics is not None and hasattr(self.diagnostics, "record"):
                self.diagnostics.record(
                    kind="dispatch_failed",
                    message="runtime event dispatch failed",
                    error=exc,
                    details={
                        "event_id": envelope.event_id,
                        "event": envelope.event,
                        "source_graph_id": envelope.source_graph_id,
                        "source_node_id": envelope.source_node_id,
                        "receiver_group": group.group_id,
                    },
                )
            self.core.graph_runtime._log_graph_event(
                envelope.source_graph_id,
                "runtime_event_dispatch_failed",
                trace_id=envelope.trace_id,
                node_instance_id=envelope.source_node_id,
                runtime_event=envelope.event,
                receiver_group=group.group_id,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _create_temporary_receiver(
        self,
        group: CompiledReceiverGroup,
        envelope: RuntimeEventEnvelope,
        profile_id: str,
    ) -> CompiledReceiver:
        profile = get_profile(profile_category_dir(AGENT_PROFILE_DIR), profile_id)
        if not isinstance(profile, dict):
            raise FileNotFoundError(f"agent profile not found: {profile_id}")
        base_node_id = str(profile.get("node_name") or profile.get("id") or profile_id).strip() or profile_id
        node_id = self._unique_node_id(group.graph_id, f"{base_node_id}_{envelope.event}_{envelope.event_id[-8:]}")
        self.core.profile_api._create_agent_node_from_profile(
            profile_id,
            profile,
            graph_id=group.graph_id,
            node_id=node_id,
            name=str(profile.get("name") or node_id).strip() or node_id,
            extra_config={
                "runtime_event_receiver": {
                    "temporary": True,
                    "receiver_group": group.group_id,
                    "profile_id": profile_id,
                    "created_for_event": envelope.event,
                    "creation_trace_id": envelope.trace_id or envelope.event_id,
                    "source_event_id": envelope.event_id,
                    "merge_target": {
                        "graph_id": group.merge_target.graph_id,
                        "node_id": group.merge_target.node_id,
                    },
                    "cleanup_status": "pending",
                }
            },
        )
        self.core.graph_runtime._log_graph_event(
            group.graph_id,
            "runtime_event_receiver_created",
            node_id=node_id,
            runtime_event=envelope.event,
            profile_id=profile_id,
            receiver_group=group.group_id,
            trace_id=envelope.trace_id,
        )
        return CompiledReceiver(group.graph_id, node_id)

    def _enqueue_receiver(
        self,
        receiver: CompiledReceiver,
        group: CompiledReceiverGroup,
        envelope: RuntimeEventEnvelope,
        *,
        profile_id: str,
        temporary: bool,
    ) -> None:
        config_path = self.core.graph_runtime._node_config_path(receiver.node_id, receiver.graph_id)
        if not config_path or not os.path.exists(config_path):
            raise FileNotFoundError(f"receiver node not found: {receiver.graph_id}/{receiver.node_id}")
        text = _dispatch_message(group, envelope, profile_id=profile_id, temporary=temporary)
        pending = {
            "payload": build_text_envelope(text, role="user"),
            "trace_id": envelope.trace_id or envelope.event_id,
            "depth": 1,
            "visited": [f"{envelope.source_graph_id}:{envelope.source_node_id}"],
            "from": envelope.source_node_id,
            "from_output_index": 0,
            "to_input_index": 0,
            "source": "runtime_event_dispatch",
            "event_id": envelope.event_id,
            "event": envelope.event,
            "receiver_group": group.group_id,
            "_runtime_owner_id": getattr(self.core, "runtime_owner_id", ""),
        }
        _append_node_pending(config_path, pending)
        self.core.graph_runtime._ensure_graph_runner(receiver.graph_id)
        self.core.graph_runtime._wake_graph_runner(receiver.graph_id)
        self.core.graph_runtime._log_graph_event(
            envelope.source_graph_id,
            "runtime_event_dispatch_enqueue",
            trace_id=envelope.trace_id,
            runtime_event=envelope.event,
            receiver_group=group.group_id,
            to_node=receiver.node_id,
            target_graph_id=receiver.graph_id,
            temporary=temporary,
            payload_preview=envelope_preview(pending["payload"]),
        )

    def _unique_node_id(self, graph_id: str, raw_base: str) -> str:
        safe_base = self.core.graph_runtime._sanitize_node_id(raw_base)[:80] or "runtime_event_receiver"
        for _ in range(100):
            candidate = self.core.graph_runtime._sanitize_node_id(f"{safe_base}_{uuid.uuid4().hex[:8]}")
            path = self.core.graph_runtime._node_config_path(candidate, graph_id)
            if path and not os.path.exists(path):
                return candidate
        raise RuntimeError("failed to allocate temporary runtime event receiver id")


def _dispatch_message(
    group: CompiledReceiverGroup,
    envelope: RuntimeEventEnvelope,
    *,
    profile_id: str,
    temporary: bool,
) -> str:
    payload = envelope.payload
    lines = [
        "Runtime event dispatch.",
        f"Event: {envelope.event}",
        f"Source: {envelope.source_graph_id}/{envelope.source_node_id}",
        f"Trace: {envelope.trace_id or envelope.event_id}",
        f"Receiver group: {group.group_id}",
    ]
    if profile_id:
        lines.append(f"Profile: {profile_id}")
    if temporary:
        lines.append("This is a temporary receiver. Produce the correction or analysis needed; backend cleanup will merge and delete this node.")
    summary_keys = (
        "message",
        "error",
        "status",
        "tool_name",
        "provider",
        "node_dir",
        "messages_path",
        "runtime_events_path",
        "user_context_path",
        "soul_context_path",
        "long_term_memory_path",
        "final_message_preview",
    )
    for key in summary_keys:
        value = payload.get(key)
        if value:
            lines.append(f"{key}: {str(value)[:1200]}")
    return "\n".join(lines)
