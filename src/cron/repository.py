"""Graph-local SQLite transactions shared by tools and the scheduler."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .schedule import AtSchedule, CreateJob, UpdateJob, next_deadline, schedule_adapter


class CronRepository:
    def __init__(self, graph_directory: Path):
        self.path = graph_directory / "cron.sqlite3"
        if not graph_directory.is_dir():
            raise FileNotFoundError(graph_directory)
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, node_id TEXT NOT NULL, name TEXT NOT NULL,
                    prompt TEXT NOT NULL, schedule TEXT NOT NULL, access_role TEXT NOT NULL,
                    enabled INTEGER NOT NULL, next_run REAL, revision INTEGER NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(node_id, name)
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, node_id TEXT NOT NULL,
                    name TEXT NOT NULL, prompt TEXT NOT NULL, access_role TEXT NOT NULL,
                    scheduled_at REAL NOT NULL, status TEXT NOT NULL,
                    started_at REAL, finished_at REAL, error TEXT,
                    UNIQUE(job_id, scheduled_at)
                );
                CREATE INDEX IF NOT EXISTS runs_status ON runs(status);
            """)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _job(row):
        item = dict(row)
        item["schedule"] = json.loads(item["schedule"])
        item["enabled"] = bool(item["enabled"])
        return item

    @staticmethod
    def _owned(db, node_id, job_id):
        row = db.execute("SELECT * FROM jobs WHERE id=? AND node_id=?", (job_id, node_id)).fetchone()
        if row is None:
            raise ValueError("schedule not found for current node")
        return row

    def create(self, node_id: str, spec: CreateJob, access_role: str, now: float) -> dict:
        if access_role not in {"developer", "nondeveloper"}:
            raise ValueError("invalid schedule access role")
        schedule_json = spec.schedule.model_dump_json()
        with self.transaction() as db:
            existing = db.execute("SELECT * FROM jobs WHERE node_id=? AND name=?", (node_id, spec.name)).fetchone()
            if existing:
                if (existing["prompt"], existing["schedule"], existing["access_role"]) != (spec.prompt, schedule_json, access_role):
                    raise ValueError("name already exists; list then update the existing schedule")
                return self._job(existing)
            deadline = next_deadline(spec.schedule, now)
            if deadline <= now:
                raise ValueError("new single-run schedule must be in the future")
            job_id = uuid.uuid4().hex
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,1,?,1,?,?)",
                       (job_id, node_id, spec.name, spec.prompt, schedule_json, access_role, deadline, now, now))
            return self._job(self._owned(db, node_id, job_id))

    def list(self, node_id: str) -> dict:
        with self.transaction() as db:
            jobs = [self._job(row) for row in db.execute("SELECT * FROM jobs WHERE node_id=? ORDER BY created_at", (node_id,))]
            runs = [dict(row) for row in db.execute(
                "SELECT * FROM runs WHERE node_id=? ORDER BY scheduled_at DESC LIMIT 30", (node_id,))]
            return {"jobs": jobs, "recent_runs": runs}

    def update(self, node_id: str, spec: UpdateJob, access_role: str, now: float) -> dict:
        if access_role not in {"developer", "nondeveloper"}:
            raise ValueError("invalid schedule access role")
        changes = spec.model_dump(exclude_unset=True)
        if len(changes) == 2 or any(value is None for value in changes.values()):
            raise ValueError("provide at least one non-null change")
        with self.transaction() as db:
            row = self._owned(db, node_id, spec.job_id)
            if row["revision"] != spec.expected_revision:
                raise ValueError("revision conflict; list schedules and retry")
            schedule = spec.schedule or schedule_adapter.validate_json(row["schedule"])
            enabled = row["enabled"] if spec.enabled is None else spec.enabled
            deadline = row["next_run"]
            if spec.schedule is not None or (spec.enabled is True and not row["enabled"]):
                deadline = next_deadline(schedule, now)
                if enabled and deadline <= now:
                    raise ValueError("resuming a past single-run schedule requires a new future schedule")
            role = "nondeveloper" if "nondeveloper" in (row["access_role"], access_role) else "developer"
            # A schedule edit invalidates queued deadlines. Content-only edits are
            # read from the outbox again at execution, including the current role.
            if spec.schedule is not None or spec.enabled is False:
                db.execute("UPDATE runs SET status='cancelled', finished_at=? WHERE job_id=? AND status='pending'", (now, spec.job_id))
            else:
                db.execute("UPDATE runs SET name=?,prompt=?,access_role=? WHERE job_id=? AND status='pending'",
                           (spec.name or row["name"], spec.prompt or row["prompt"], role, spec.job_id))
            db.execute("""UPDATE jobs SET name=?,prompt=?,schedule=?,access_role=?,enabled=?,next_run=?,
                       revision=revision+1,updated_at=? WHERE id=?""",
                       (spec.name or row["name"], spec.prompt or row["prompt"], schedule.model_dump_json(),
                        role, int(enabled), deadline, now, spec.job_id))
            return self._job(self._owned(db, node_id, spec.job_id))

    def delete(self, node_id: str, job_id: str, revision: int, now: float):
        with self.transaction() as db:
            row = self._owned(db, node_id, job_id)
            if row["revision"] != revision:
                raise ValueError("revision conflict; list schedules and retry")
            db.execute("UPDATE runs SET status='cancelled',finished_at=? WHERE job_id=? AND status='pending'", (now, job_id))
            db.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    def materialize_due(self, now: float):
        with self.transaction() as db:
            rows = db.execute("SELECT * FROM jobs WHERE enabled=1 AND next_run<=?", (now,)).fetchall()
            for row in rows:
                active = db.execute("SELECT 1 FROM runs WHERE job_id=? AND status IN ('pending','running')", (row["id"],)).fetchone()
                schedule = schedule_adapter.validate_json(row["schedule"])
                if active and isinstance(schedule, AtSchedule):
                    # A newly scheduled one-shot must wait for a previous execution,
                    # rather than being consumed without ever creating its run.
                    continue
                if not active:
                    db.execute("INSERT INTO runs (id,job_id,node_id,name,prompt,access_role,scheduled_at,status) VALUES (?,?,?,?,?,?,?,'pending')",
                               ("cron-" + uuid.uuid4().hex, row["id"], row["node_id"], row["name"], row["prompt"], row["access_role"], row["next_run"]))
                deadline = next_deadline(schedule, now, row["next_run"])
                db.execute("UPDATE jobs SET next_run=?,enabled=?,updated_at=? WHERE id=?", (deadline, int(deadline is not None), now, row["id"]))

    def pending_runs(self) -> list[dict]:
        with self.transaction() as db:
            return [dict(row) for row in db.execute("SELECT * FROM runs WHERE status='pending' ORDER BY scheduled_at")]

    def recover_interrupted(self):
        with self.transaction() as db:
            db.execute("UPDATE runs SET status='pending',error='Backend interrupted; replay pending' WHERE status='running'")

    def begin_run(self, run_id: str, node_id: str, now: float) -> dict | None:
        with self.transaction() as db:
            row = db.execute("SELECT * FROM runs WHERE id=? AND node_id=? AND status='pending'", (run_id, node_id)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE runs SET status='running',started_at=?,error=NULL WHERE id=?", (now, run_id))
            return dict(row)

    def finish_run(self, run_id: str, now: float, error: str | None = None):
        with self.transaction() as db:
            db.execute("UPDATE runs SET status=?,finished_at=?,error=? WHERE id=? AND status='running'",
                       ("failed" if error else "completed", now, error, run_id))

    def delivery_error(self, run_id: str, error: str):
        with self.transaction() as db:
            db.execute("UPDATE runs SET error=? WHERE id=? AND status='pending'", (error, run_id))
