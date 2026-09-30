from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .contracts import AgentGroup, GroupConflict, GroupNotFound, GroupPermissionError
from .migrations import upgrade_task_notifications


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class GroupRepository:
    """One graph's durable board, membership index, ordered events and outbox.

    BEGIN IMMEDIATE serializes writers across processes. The membership index and
    document are updated in the same transaction, as are events and recipients.
    No mutation rewrites the graph's canvas/configuration file.
    """

    def __init__(self, graph_directory: Path, *, access_role: str = "developer"):
        if access_role not in ("developer", "nondeveloper"):
            raise ValueError("unknown collaboration access role")
        self.access_role = access_role
        self.path = graph_directory / "groups.sqlite3"
        if not graph_directory.is_dir():
            raise GroupNotFound("graph directory does not exist")
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3, 4):
                raise GroupConflict(f"unsupported group store version: {version}")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS groups (
                    id TEXT PRIMARY KEY, document TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS members (
                    node_id TEXT PRIMARY KEY,
                    group_id TEXT NOT NULL REFERENCES groups(id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL REFERENCES groups(id),
                    kind TEXT NOT NULL, actor_id TEXT, payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_by_group ON events(group_id, seq);
                CREATE TABLE IF NOT EXISTS deliveries (
                    event_seq INTEGER NOT NULL REFERENCES events(seq),
                    node_id TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending'
                        CHECK(state IN ('pending', 'delivered', 'cancelled')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    PRIMARY KEY(event_seq, node_id)
                );
                CREATE TABLE IF NOT EXISTS delivery_progress (
                    event_seq INTEGER NOT NULL, node_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    PRIMARY KEY(event_seq,node_id),
                    FOREIGN KEY(event_seq,node_id) REFERENCES deliveries(event_seq,node_id) ON UPDATE CASCADE ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS message_requests (
                    group_id TEXT NOT NULL, actor_key TEXT NOT NULL,
                    request_id TEXT NOT NULL, command TEXT NOT NULL,
                    event_seq INTEGER NOT NULL REFERENCES events(seq),
                    PRIMARY KEY(group_id, actor_key, request_id)
                );

            """)
            if version < 2:
                # One-time upgrade: structural history must not restart models,
                # including outbox entries made before this policy was corrected.
                db.executescript("""
                    BEGIN IMMEDIATE;
                    UPDATE deliveries SET state='cancelled'
                    WHERE state='pending' AND event_seq IN (
                        SELECT seq FROM events WHERE kind IN (
                            'group_created', 'group_dissolved', 'member_joined',
                            'member_left', 'member_restored', 'member_renamed',
                            'member_role_updated', 'group_visibility_changed'
                        )
                    );
                    PRAGMA user_version=2;
                    COMMIT;
                """)

            if version < 4:
                upgrade_task_notifications(db)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def read(db, group_id: str, actor_id: str | None = None) -> AgentGroup:
        row = db.execute("SELECT document FROM groups WHERE id=?", (group_id,)).fetchone()
        if row is None:
            raise GroupNotFound("group not found")
        group = AgentGroup.model_validate_json(row["document"])
        if group.dissolved:
            raise GroupNotFound("group has been dissolved")
        if actor_id is not None and actor_id not in {m.node_id for m in group.members}:
            raise GroupPermissionError("actor is not a current group member")
        return group

    @staticmethod
    def save(db, group: AgentGroup, *, bump: bool = True):
        if bump:
            group.revision += 1
            group.updated_at = timestamp()
        db.execute("INSERT INTO groups VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET document=excluded.document",
                   (group.id, group.model_dump_json()))

    def event(self, db, group: AgentGroup, kind: str, actor_id: str | None, payload: dict,
              *, recipients: list[str], notify_actor: bool = False) -> dict:
        created = timestamp()
        payload = {**payload, "group_revision": group.revision, "_access_role": self.access_role}
        cursor = db.execute("INSERT INTO events(group_id,kind,actor_id,payload,created_at) VALUES(?,?,?,?,?)",
                            (group.id, kind, actor_id, json.dumps(payload, ensure_ascii=False), created))
        seq = cursor.lastrowid
        targets = recipients
        db.executemany("INSERT INTO deliveries(event_seq,node_id) VALUES(?,?)",
                       [(seq, target) for target in set(targets) if notify_actor or target != actor_id])
        return {"seq": seq, "group_id": group.id, "kind": kind, "actor_id": actor_id,
                "payload": payload, "created_at": created}

    def get(self, group_id: str, actor_id: str | None = None) -> AgentGroup:
        with self.connect() as db:
            return self.read(db, group_id, actor_id)

    def list(self) -> list[AgentGroup]:
        with self.connect() as db:
            groups = [AgentGroup.model_validate_json(r[0]) for r in db.execute("SELECT document FROM groups ORDER BY rowid")]
        return [group for group in groups if not group.dissolved]

    def member_group(self, node_id: str) -> AgentGroup | None:
        with self.connect() as db:
            row = db.execute("SELECT group_id FROM members WHERE node_id=?", (node_id,)).fetchone()
            return self.read(db, row[0], node_id) if row else None

    def events(self, group_id: str, actor_id: str | None = None, *, after: int = 0, limit: int = 100, latest: bool = False, before: int = 0):
        if after < 0 or not 1 <= limit <= 500:
            raise ValueError("invalid event pagination")
        with self.connect() as db:
            self.read(db, group_id, actor_id)
            if latest or before:
                rows = db.execute("SELECT * FROM events WHERE group_id=? AND (?=0 OR seq<?) ORDER BY seq DESC LIMIT ?",
                                  (group_id, before, before, limit)).fetchall()[::-1]
            else:
                rows = db.execute("SELECT * FROM events WHERE group_id=? AND seq>? ORDER BY seq LIMIT ?",
                                  (group_id, after, limit)).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["payload"] = json.loads(item["payload"])
                recipient = item["payload"].get("recipient_id")
                if actor_id is None or not recipient or actor_id in (recipient, item["actor_id"]):
                    result.append(item)
            oldest = rows[0]["seq"] if rows else 0
            has_older = bool(oldest and db.execute("SELECT 1 FROM events WHERE group_id=? AND seq<? LIMIT 1",
                                                 (group_id, oldest)).fetchone())
            return {"events": result, "cursor": rows[-1]["seq"] if rows else after, "has_older": has_older}

    def pending_deliveries(self, limit: int = 100):
        with self.connect() as db:
            rows = db.execute("""SELECT e.*,d.node_id,d.attempts,d.last_error,
                ROW_NUMBER() OVER(PARTITION BY e.group_id,d.node_id ORDER BY e.seq) AS delivery_slot FROM deliveries d
                JOIN events e ON e.seq=d.event_seq WHERE d.state='pending'
                ORDER BY delivery_slot,e.seq,d.node_id LIMIT ?""", (limit,)).fetchall()
            return [{**{key: row[key] for key in row.keys() if key != "delivery_slot"},
                     "payload": json.loads(row["payload"])} for row in rows]

    def record_delivery(self, seq: int, node_id: str, *, error: str | None = None):
        with self.transaction() as db:
            result = db.execute("""UPDATE deliveries SET attempts=attempts+1,last_error=?,state=?
                WHERE event_seq=? AND node_id=? AND state='pending'""",
                (error, "pending" if error is not None else "delivered", seq, node_id))
            return result.rowcount == 1
