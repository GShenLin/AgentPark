from __future__ import annotations

import threading
import time
import uuid

from .store import MemoryStore


class LeaseLost(RuntimeError):
    pass


class PipelineLease:
    """SQLite ownership spans processes; a heartbeat covers slow model requests."""

    def __init__(self, store: MemoryStore, seconds: int):
        self.store, self.seconds = store, seconds
        self.token = uuid.uuid4().hex
        self.stop = threading.Event()
        self.failure: BaseException | None = None
        self.thread: threading.Thread | None = None

    def claim(self) -> bool:
        now = time.time()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE name='pipeline'").fetchone()
            if row and (row["lease_until"] > now or row["retry_at"] > now):
                return False
            db.execute("""INSERT INTO jobs(name,token,lease_until,status) VALUES('pipeline',?,?,'running')
                ON CONFLICT(name) DO UPDATE SET token=excluded.token,lease_until=excluded.lease_until,
                status='running',error='',retry_at=0""", (self.token, now + self.seconds))
        self.thread = threading.Thread(target=self._heartbeat, daemon=True, name="memory-lease")
        self.thread.start()
        return True

    def _heartbeat(self):
        while not self.stop.wait(max(0.1, self.seconds / 3)):
            try:
                with self.store.connect() as db:
                    changed = db.execute("UPDATE jobs SET lease_until=? WHERE name='pipeline' AND token=? AND lease_until>?",
                                         (time.time() + self.seconds, self.token, time.time())).rowcount
                    if changed != 1:
                        raise LeaseLost("memory pipeline lease was replaced or expired")
            except BaseException as exc:
                self.failure = exc
                return

    def check(self, db) -> None:
        if self.failure:
            raise LeaseLost("memory heartbeat failed") from self.failure
        row = db.execute("SELECT token,lease_until FROM jobs WHERE name='pipeline'").fetchone()
        if not row or row["token"] != self.token or row["lease_until"] <= time.time():
            raise LeaseLost("memory pipeline no longer owns its lease")

    def finish(self, *, error: str = "", retry_seconds: int = 0):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
        with self.store.connect() as db:
            db.execute("""UPDATE jobs SET lease_until=0,status=?,error=?,retry_at=?
                WHERE name='pipeline' AND token=?""",
                       ("failed" if error else "succeeded", error,
                        time.time() + retry_seconds if error and retry_seconds > 0 else 0, self.token))
