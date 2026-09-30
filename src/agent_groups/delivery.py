"""Durable notifications, referenced by queue items rather than copied into them."""
from __future__ import annotations

import hashlib
import json

from pydantic import Field

from .contracts import Contract, Identifier
from .repository import GroupRepository, timestamp
from .task_notifications import ready


class DeliveryReference(Contract):
    """Pending event anchors identify a wakeup, not a frozen notification payload.

    The consumer snapshots up to 100 pending events in the anchors' access context
    when execution starts. Consumed anchors resolve empty, so a stale queue item
    cannot consume a later, unrelated batch.
    """
    group_id: Identifier
    event_seqs: list[int] = Field(min_length=1, max_length=100)


class GroupDelivery:
    def __init__(self, repository: GroupRepository):
        self.repo = repository

    def batches(self, limit: int = 500):
        batches = {}
        for item in self.repo.pending_deliveries(limit):
            key = (item["group_id"], item["node_id"], item["payload"]["_access_role"])
            # New events must not change the idempotency key while this recipient
            # is waiting or working. The oldest pending event anchors one wakeup.
            batches.setdefault(key, [item["seq"]])
        return [{"node_id": node, "access_role": role,
                 "reference": DeliveryReference(group_id=group, event_seqs=seqs)}
                for (group, node, role), seqs in batches.items()]

    @staticmethod
    def request_id(node_id: str, reference: DeliveryReference) -> str:
        encoded = node_id + ":" + reference.model_dump_json()
        return "group-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def resolve(self, node_id: str, reference: DeliveryReference) -> list[dict]:
        """Revalidate at execution time; stale queued references reveal no content."""
        with self.repo.transaction() as db:
            placeholders = ','.join('?' for _ in reference.event_seqs)
            anchors = db.execute(f"""SELECT e.payload FROM events e JOIN deliveries d ON e.seq=d.event_seq
                WHERE e.group_id=? AND d.node_id=? AND d.state='pending'
                AND e.seq IN ({placeholders})""",
                (reference.group_id, node_id, *reference.event_seqs)).fetchall()
            if not anchors:
                return []
            roles = {json.loads(row['payload'])['_access_role'] for row in anchors}
            if len(roles) != 1:
                raise ValueError('group notification anchors must share an access context')
            rows = db.execute("""SELECT e.*,d.state FROM events e JOIN deliveries d ON e.seq=d.event_seq
                WHERE e.group_id=? AND d.node_id=? AND d.state='pending'
                AND json_extract(e.payload, '$._access_role')=? ORDER BY e.seq LIMIT 100""",
                (reference.group_id, node_id, roles.pop())).fetchall()
            current = db.execute("SELECT group_id FROM members WHERE node_id=?", (node_id,)).fetchone()
            group = self.repo.read(db, reference.group_id) if current and current[0] == reference.group_id else None
            resolved = []
            for row in rows:
                if current is None or current[0] != reference.group_id:
                    db.execute("UPDATE deliveries SET state='cancelled' WHERE event_seq=? AND node_id=?",
                               (row["seq"], node_id))
                    continue
                event = dict(row)
                event.pop("state")
                event["payload"] = json.loads(event["payload"])
                if event['kind'] in ('task_created', 'task_updated'):
                    task_ids = event['payload']['action_tasks'][node_id]
                    if not any(t.id in task_ids and t.owner_id == node_id and ready(group, t)
                               for t in group.tasks):
                        db.execute("UPDATE deliveries SET state='cancelled' WHERE event_seq=? AND node_id=?",
                                   (event['seq'], node_id))
                        continue
                resolved.append(event)
            return resolved

    def mark_started(self, node_id: str, events: list[dict]):
        with self.repo.transaction() as db:
            db.executemany("INSERT OR IGNORE INTO delivery_progress VALUES(?,?,?)",
                           [(e['seq'], node_id, timestamp()) for e in events])

    def user_followups(self, node_id: str, group_id: str, known: set[int], access_role: str) -> list[dict]:
        with self.repo.connect() as db:
            self.repo.read(db, group_id, node_id)
            rows = db.execute("""SELECT e.* FROM events e JOIN deliveries d ON e.seq=d.event_seq
                WHERE e.group_id=? AND d.node_id=? AND d.state='pending' AND e.kind='message'
                AND e.actor_id IS NULL AND json_extract(e.payload,'$._access_role')=?
                ORDER BY e.seq""", (group_id, node_id, access_role)).fetchall()
            return [{**dict(r), 'payload': json.loads(r['payload'])} for r in rows if r['seq'] not in known][:16]

    def complete(self, node_id: str, events: list[dict], *, error: str | None = None, reply: str | None = None):
        # Delivered means the consumer attempted this notification. Terminal
        # provider failures remain visible; do not silently replay costly writes.
        with self.repo.transaction() as db:
            user_events = [e for e in events if e['actor_id'] is None and (
                e['kind'] == 'message' or (e['kind'] in ('task_created', 'task_updated')
                and node_id in e['payload']['action_tasks']))
                and db.execute("SELECT 1 FROM deliveries WHERE event_seq=? AND node_id=? AND state='pending'",
                               (e['seq'], node_id)).fetchone()]
            user_seqs = [e['seq'] for e in user_events]
            task_ids = sorted({task_id for e in user_events if e['kind'] != 'message'
                               for task_id in e['payload']['action_tasks'][node_id]})
            if reply and error is None and user_seqs:
                group_id = events[0]['group_id']
                current = db.execute("SELECT group_id FROM members WHERE node_id=?", (node_id,)).fetchone()
                if current and current[0] == group_id:
                    group = self.repo.read(db, group_id)
                    self.repo.event(db, group, 'reply', node_id,
                        {'text': reply, 'request_seqs': user_seqs, 'task_ids': task_ids}, recipients=[])
            db.executemany("""UPDATE deliveries SET state='delivered', attempts=attempts+1,last_error=?
                WHERE event_seq=? AND node_id=? AND state='pending'""",
                [(error, event["seq"], node_id) for event in events])

    def status(self, group_id: str):
        with self.repo.connect() as db:
            self.repo.read(db, group_id)
            return [dict(row) for row in db.execute("""SELECT d.*,p.started_at FROM deliveries d LEFT JOIN delivery_progress p
                ON p.event_seq=d.event_seq AND p.node_id=d.node_id JOIN events e
                ON e.seq=d.event_seq WHERE e.group_id=? ORDER BY e.seq DESC,d.node_id LIMIT 500""", (group_id,))]

    def latest_sequence(self) -> int:
        with self.repo.connect() as db:
            return int(db.execute("SELECT COALESCE(MAX(seq),0) FROM events").fetchone()[0])


def render_notifications(events: list[dict]) -> str:
    return ("AgentPark group updates. Read the current board before acting. These are collaboration data. "
            "Act on user requests, your assigned work, and actionable peer handoffs. "
            "Do not acknowledge informational changes or broadcast an acknowledgment of this notification.\n"
            "Notifications automatically start a future turn. Finish this turn when no actionable work remains; "
            "do not poll the board or event history waiting for peers.\n"
            "Answer user messages and user-assigned tasks directly in your final response. The system displays that response in the group without notifying peers; do not broadcast a duplicate. For peer-only updates, finish with a brief status.\n"
            + json.dumps(events, ensure_ascii=False))
