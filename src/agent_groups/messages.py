from __future__ import annotations

import json

from .contracts import GroupConflict, GroupPermissionError, PublishMessage
from .repository import GroupRepository


class GroupMessages:
    def __init__(self, repository: GroupRepository):
        self.repo = repository

    def publish(self, group_id: str, command: PublishMessage, actor_id: str | None) -> dict:
        with self.repo.transaction() as db:
            group = self.repo.read(db, group_id, actor_id)
            members = {member.node_id for member in group.members}
            if command.recipient_id is not None and command.recipient_id not in members:
                raise GroupPermissionError("recipient must be a current group member")
            if command.recipient_id is not None and command.recipient_id == actor_id:
                raise GroupConflict("send to a teammate, not yourself")
            if (actor_id is not None and command.intent == "action"
                    and command.recipient_id is None and not command.broadcast_reason.strip()):
                raise GroupConflict("peer actions require recipient_id; use group_post_update for shared status "
                                    "or group_broadcast_message with a reason why all members must act")
            actor_key = "user" if actor_id is None else "node:" + actor_id
            encoded = command.model_dump_json(exclude={"attachments"} if not command.attachments else set())
            previous = db.execute("""SELECT command,event_seq FROM message_requests
                WHERE group_id=? AND actor_key=? AND request_id=?""",
                (group_id, actor_key, command.request_id)).fetchone()
            if previous:
                if previous["command"] != encoded:
                    raise GroupConflict("request_id was already used for another message")
                row = dict(db.execute("SELECT * FROM events WHERE seq=?", (previous["event_seq"],)).fetchone())
                row["payload"] = json.loads(row["payload"])
                return row
            recipients = ([] if command.intent == "update" else
                          [command.recipient_id] if command.recipient_id else [m.node_id for m in group.members])
            event = self.repo.event(db, group, "update" if command.intent == "update" else "message", actor_id,
                                   {"text": command.text, "recipient_id": command.recipient_id,
                                    "intent": command.intent, "broadcast_reason": command.broadcast_reason,
                                    "attachments": [item.model_dump() for item in command.attachments]},
                                   recipients=recipients)
            db.execute("INSERT INTO message_requests VALUES(?,?,?,?,?)",
                       (group_id, actor_key, command.request_id, encoded, event["seq"]))
            return event
