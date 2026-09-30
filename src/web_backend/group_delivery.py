"""Application-lifetime outbox pump and the node execution notification boundary."""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from src.agent_groups.delivery import DeliveryReference, GroupDelivery, render_notifications
from src.agent_groups.repository import GroupRepository
from src.message_protocol import build_text_envelope
from src.message_resources import build_resource_part
from . import runtime_paths

logger = logging.getLogger(__name__)


class GroupDeliveryService:
    def __init__(self, core):
        self.core = core
        self.stop = threading.Event()
        self.thread = None
        self.versions = {}
        self.retry_at = {}

    def start(self):
        if self.thread is not None:
            raise RuntimeError("group delivery service is already started")
        self.stop.clear()
        self.thread = threading.Thread(target=self._run, name="group-delivery", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread is not None:
            self.thread.join(timeout=20)
            if self.thread.is_alive():
                raise RuntimeError("group delivery service did not stop")
            self.thread = None

    def _run(self):
        while not self.stop.is_set():
            for path in Path(runtime_paths._get_graphs_dir()).glob("*/groups.sqlite3"):
                if self.stop.is_set():
                    break
                try:
                    self.poll_graph(path.parent)
                except Exception:
                    logger.exception("Group notification polling failed for %s", path.parent.name)
            self.stop.wait(1)

    def poll_graph(self, directory: Path):
        graph_id = directory.name
        repo = GroupRepository(directory)
        delivery = GroupDelivery(repo)
        sequence = delivery.latest_sequence()
        if self.versions.get(graph_id) != sequence:
            # No task/message/member data goes to the public invalidation stream.
            self.core.graph_events.publish(graph_id, {"event": "groups_changed"})
            self.versions[graph_id] = sequence
        for batch in delivery.batches():
            if self.stop.is_set():
                break
            node_id, reference = batch["node_id"], batch["reference"]
            request_id = delivery.request_id(node_id, reference)
            retry_key = (graph_id, request_id)
            if time.monotonic() < self.retry_at.get(retry_key, 0):
                continue
            envelope = build_text_envelope("Group updates are available.", role="user")
            envelope["parts"].append({"type": "meta", "meta": {"group_delivery": reference.model_dump()}})
            try:
                self.core.node_ops.enqueue_node_instance_pending(node_id, {
                    "payload": envelope, "source": "group_notice",
                    "trace_id": request_id, "idempotency_key": request_id,
                    "_access_role": batch["access_role"],
                }, graph_id=graph_id)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                for seq in reference.event_seqs:
                    repo.record_delivery(seq, node_id, error=error)
                self.retry_at[retry_key] = time.monotonic() + 10
                logger.exception("Group notification enqueue failed: graph=%s node=%s", graph_id, node_id)
            else:
                self.retry_at.pop(retry_key, None)
                # Queue state is in memory. Keep the durable outbox pending until
                # execution finishes; repeated polls use the same idempotency key.


class GroupNotificationRun:
    def __init__(self, *, config_path: str, node_id: str, envelope: dict):
        references = [part["meta"]["group_delivery"] for part in envelope.get("parts", [])
                      if part.get("type") == "meta" and "group_delivery" in part.get("meta", {})]
        if len(references) != 1:
            raise ValueError("group notification requires exactly one delivery reference")
        reference = DeliveryReference.model_validate(references[0])
        self.delivery = GroupDelivery(GroupRepository(Path(config_path).parent.parent))
        self.node_id = node_id
        self.group_id = reference.group_id
        self.events = self.delivery.resolve(node_id, reference)
        self.access_role = "nondeveloper" if any(event["payload"]["_access_role"] == "nondeveloper"
                                                for event in self.events) else "developer"
        self.delivery.mark_started(node_id, self.events)
        self.message = self.build_message(self.events)

    def build_message(self, events):
        message = build_text_envelope(render_notifications(events), role="user")
        for event in events:
            if event["kind"] != "message":
                continue
            for attachment in event["payload"].get("attachments", []):
                message["parts"].append(build_resource_part(
                    **attachment, resource_id=f"group-{self.group_id}-{event['seq']}-{len(message['parts'])}",
                    metadata={"group_id": self.group_id, "event_seq": event["seq"],
                              "actor_id": event["actor_id"]},
                ))

        return message

    def consume_followups(self):
        from src.agent_groups.contracts import GroupNotFound, GroupPermissionError
        try:
            events = self.delivery.user_followups(self.node_id, self.group_id,
                {e['seq'] for e in self.events}, self.access_role)
        except (GroupNotFound, GroupPermissionError):
            return []  # A dissolved group or revoked membership cannot inject more content.
        if not events:
            return []
        self.delivery.mark_started(self.node_id, events)
        self.events.extend(events)
        return [self.build_message(events)]

    def complete(self, *, error: str | None = None, reply: str | None = None):
        self.delivery.complete(self.node_id, self.events, error=error, reply=reply)
