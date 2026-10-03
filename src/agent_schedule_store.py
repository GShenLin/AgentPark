"""Durable, owner-scoped schedules and transactional occurrence outbox."""
from __future__ import annotations

import json
import math
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class AgentScheduleStore:
    """Each operation uses a short transaction; no execution occurs inside the store."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS agent_schedules (
                    schedule_id TEXT PRIMARY KEY, graph_id TEXT NOT NULL,
                    node_id TEXT NOT NULL, task_id TEXT NOT NULL,
                    prompt TEXT NOT NULL, access_metadata TEXT NOT NULL,
                    run_at REAL NOT NULL, interval_seconds REAL,
                    status TEXT NOT NULL, revision INTEGER NOT NULL,
                    idempotency_key TEXT NOT NULL, request_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    UNIQUE(graph_id, node_id, task_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS agent_schedule_deliveries (
                    occurrence_id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL REFERENCES agent_schedules(schedule_id),
                    graph_id TEXT NOT NULL, node_id TEXT NOT NULL,
                    task_id TEXT NOT NULL, prompt TEXT NOT NULL,
                    access_metadata TEXT NOT NULL, scheduled_at REAL NOT NULL,
                    status TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS agent_schedules_due
                    ON agent_schedules(status, run_at);
                CREATE INDEX IF NOT EXISTS agent_schedule_delivery_pending
                    ON agent_schedule_deliveries(schedule_id, status);
            """)

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _text(value, name, limit=256):
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f"{name} must be a nonempty string of at most {limit} characters")
        return value

    @staticmethod
    def _number(value, name, minimum=0):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a finite number")
        try:
            valid = math.isfinite(value) and value > 0 and value >= minimum
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError(f"{name} must be positive and at least {minimum}")
        return float(value)

    @staticmethod
    def _iso(timestamp):
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")

    @classmethod
    def _time(cls, value):
        if not isinstance(value, str) or len(value) > 128:
            raise ValueError("run_at must be an ISO datetime with an explicit offset")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("offset required")
            return parsed.timestamp()
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError("run_at must be an ISO datetime with an explicit offset") from exc

    @classmethod
    def _timing(cls, params, now, required=True):
        keys = {"run_at", "delay_seconds"} & params.keys()
        if len(keys) != 1:
            if not keys and not required:
                return None
            raise ValueError("provide exactly one of run_at or delay_seconds")
        stamp = (cls._time(params["run_at"]) if "run_at" in keys else
                 now + cls._number(params["delay_seconds"], "delay_seconds"))
        stamp = round(stamp, 6)
        if stamp <= now:
            raise ValueError("run_at must be in the future")
        try:
            cls._iso(stamp)
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError("run_at exceeds the supported date range") from exc
        return stamp

    @classmethod
    def _schedule(cls, row, db):
        result = dict(row)
        result.pop("request_json", None)
        latest = db.execute("SELECT status FROM agent_schedule_deliveries WHERE schedule_id=? ORDER BY rowid DESC LIMIT 1", (row["schedule_id"],)).fetchone()
        result["last_delivery_status"] = latest["status"] if latest else None
        result["access_metadata"] = json.loads(result["access_metadata"])
        for name in ("run_at", "created_at"):
            result[name] = cls._iso(result[name])
        return result

    @classmethod
    def _delivery(cls, row):
        result = dict(row)
        result["access_metadata"] = json.loads(result["access_metadata"])
        result["scheduled_at"] = cls._iso(result["scheduled_at"])
        return result

    def manage(self, owner: dict, action: str, **params) -> dict:
        if not isinstance(owner, dict):
            raise ValueError("owner must be a dict")
        graph = self._text(owner.get("graph_id"), "graph_id")
        node = self._text(owner.get("node_id"), "node_id")
        if action not in {"create", "list", "get", "update", "cancel"}:
            raise ValueError("unknown schedule action")
        allowed = {
            "create": {"prompt", "run_at", "delay_seconds", "interval_seconds", "idempotency_key"},
            "list": set(), "get": {"schedule_id"},
            "cancel": {"schedule_id", "expected_revision"},
            "update": {"schedule_id", "expected_revision", "prompt", "run_at", "delay_seconds", "interval_seconds"},
        }
        if params.keys() - allowed[action]:
            raise ValueError("unknown schedule parameters")
        now = time.time()
        with self._transaction() as db:
            if action == "create":
                return self._create(db, owner, graph, node, params, now)
            if action == "list":
                rows = db.execute("SELECT * FROM agent_schedules WHERE graph_id=? AND node_id=? ORDER BY created_at, schedule_id", (graph, node))
                return {"schedules": [self._schedule(row, db) for row in rows]}
            schedule_id = self._text(params.get("schedule_id"), "schedule_id")
            row = db.execute("SELECT * FROM agent_schedules WHERE schedule_id=? AND graph_id=? AND node_id=?", (schedule_id, graph, node)).fetchone()
            if row is None:
                raise KeyError("schedule not found")
            if action == "get":
                return self._schedule(row, db)
            revision = params.get("expected_revision")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision != row["revision"]:
                raise ValueError("expected_revision does not match current revision")
            if action == "cancel":
                db.execute("UPDATE agent_schedules SET status='cancelled', revision=revision+1 WHERE schedule_id=?", (schedule_id,))
            else:
                self._update(db, row, params, now)
            if action == "cancel" or {"run_at", "delay_seconds"} & params.keys():
                db.execute("UPDATE agent_schedule_deliveries SET status='cancelled' WHERE schedule_id=? AND status='pending'", (schedule_id,))
            elif action == "update":
                db.execute("UPDATE agent_schedule_deliveries SET prompt=? WHERE schedule_id=? AND status='pending'", (params.get("prompt", row["prompt"]), schedule_id))
            return self._schedule(db.execute("SELECT * FROM agent_schedules WHERE schedule_id=?", (schedule_id,)).fetchone(), db)

    def _create(self, db, owner, graph, node, params, now):
        key = self._text(params.get("idempotency_key"), "idempotency_key")
        task = self._text(owner.get("task_id"), "task_id")
        prompt = self._text(params.get("prompt"), "prompt", 16000)
        metadata = owner.get("access_metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("access_metadata must be a dict")
        try:
            metadata_json = json.dumps(metadata, sort_keys=True, allow_nan=False)
            request = json.dumps(params, sort_keys=True, allow_nan=False)
        except (ValueError, TypeError) as exc:
            raise ValueError("schedule parameters must be JSON serializable") from exc
        if len(metadata_json) > 65536:
            raise ValueError("access_metadata exceeds size limit")
        existing = db.execute("SELECT * FROM agent_schedules WHERE graph_id=? AND node_id=? AND task_id=? AND idempotency_key=?", (graph, node, task, key)).fetchone()
        if existing:
            if existing["request_json"] != request:
                raise ValueError("idempotency_key already used for a different request")
            return self._schedule(existing, db)
        run_at = self._timing(params, now)
        interval = params.get("interval_seconds")
        if interval is not None:
            interval = self._number(interval, "interval_seconds", 60)
            self._validate_next_time(run_at, interval)
        schedule_id = str(uuid.uuid4())
        db.execute("INSERT INTO agent_schedules VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            schedule_id, graph, node, task, prompt, metadata_json, run_at,
            interval, "active", 1, key, request, now,
        ))
        return self._schedule(db.execute("SELECT * FROM agent_schedules WHERE schedule_id=?", (schedule_id,)).fetchone(), db)

    def _validate_next_time(self, run_at, interval):
        try:
            self._iso(run_at + interval)
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError("interval_seconds exceeds the supported date range") from exc

    def _update(self, db, row, params, now):
        if row["status"] == "cancelled":
            raise ValueError("cancelled schedules cannot be updated")
        if not params.keys() & {"prompt", "run_at", "delay_seconds", "interval_seconds"}:
            raise ValueError("update requires at least one changed field")
        prompt = self._text(params.get("prompt", row["prompt"]), "prompt", 16000)
        run_at = self._timing(params, now, required=False)
        if run_at is None:
            run_at = row["run_at"]
        interval = params.get("interval_seconds", row["interval_seconds"])
        if interval is not None:
            interval = self._number(interval, "interval_seconds", 60)
            self._validate_next_time(run_at, interval)
        status = "active" if {"run_at", "delay_seconds"} & params.keys() else row["status"]
        pending = db.execute("SELECT scheduled_at FROM agent_schedule_deliveries WHERE schedule_id=? AND status='pending'", (row["schedule_id"],)).fetchone()
        if pending and "interval_seconds" in params and not {"run_at", "delay_seconds"} & params.keys():
            if interval is None:
                status = "completed"
            else:
                anchor = pending["scheduled_at"]
                run_at = round(anchor + max(1, math.floor((now - anchor) / interval) + 1) * interval, 6)
                self._validate_next_time(run_at, interval)
                status = "active"
        db.execute("UPDATE agent_schedules SET prompt=?,run_at=?,interval_seconds=?,status=?,revision=revision+1 WHERE schedule_id=?", (prompt, run_at, interval, status, row["schedule_id"]))

    def due(self, now=None) -> list:
        if now is None:
            now = time.time()
        elif isinstance(now, datetime):
            if now.tzinfo is None:
                raise ValueError("now requires a timezone")
            now = now.timestamp()
        elif isinstance(now, str):
            now = self._time(now)
        else:
            now = self._number(now, "now")
        with self._transaction() as db:
            rows = db.execute("""SELECT * FROM agent_schedules s WHERE status='active' AND run_at<=?
                AND NOT EXISTS (SELECT 1 FROM agent_schedule_deliveries d
                    WHERE d.schedule_id=s.schedule_id AND d.status IN ('pending','running'))""", (now,)).fetchall()
            for row in rows:
                occurrence = str(uuid.uuid5(uuid.UUID(row["schedule_id"]), f'{row["revision"]}:{row["run_at"]:.6f}'))
                db.execute("INSERT INTO agent_schedule_deliveries VALUES (?,?,?,?,?,?,?,?,?)", (
                    occurrence, row["schedule_id"], row["graph_id"], row["node_id"], row["task_id"],
                    row["prompt"], row["access_metadata"], row["run_at"], "pending"))
                interval = row["interval_seconds"]
                if interval is None:
                    db.execute("UPDATE agent_schedules SET status='completed' WHERE schedule_id=?", (row["schedule_id"],))
                else:
                    following = round(row["run_at"] + (math.floor((now - row["run_at"]) / interval) + 1) * interval, 6)
                    db.execute("UPDATE agent_schedules SET run_at=? WHERE schedule_id=?", (following, row["schedule_id"]))
            return [self._delivery(row) for row in db.execute("SELECT * FROM agent_schedule_deliveries WHERE status IN ('pending','running') ORDER BY scheduled_at, occurrence_id")]

    def begin(self, occurrence_id, graph_id, node_id) -> dict | None:
        with self._transaction() as db:
            row = db.execute("""SELECT d.* FROM agent_schedule_deliveries d
                JOIN agent_schedules s ON s.schedule_id=d.schedule_id
                WHERE occurrence_id=? AND d.graph_id=? AND d.node_id=?
                AND d.status='pending' AND s.status!='cancelled'""", (occurrence_id, graph_id, node_id)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE agent_schedule_deliveries SET status='running' WHERE occurrence_id=?", (occurrence_id,))
            result = self._delivery(row)
            result["status"] = "running"
            return result

    def finish(self, occurrence_id, status="completed") -> None:
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError("invalid terminal delivery status")
        with self._transaction() as db:
            db.execute("UPDATE agent_schedule_deliveries SET status=? WHERE occurrence_id=? AND status IN ('pending','running')", (status, occurrence_id))

    def reset_running(self) -> None:
        with self._transaction() as db:
            db.execute("""UPDATE agent_schedule_deliveries SET status=CASE
                WHEN EXISTS (SELECT 1 FROM agent_schedules s WHERE s.schedule_id=agent_schedule_deliveries.schedule_id AND s.status='cancelled')
                THEN 'cancelled' ELSE 'pending' END WHERE status='running'""")
