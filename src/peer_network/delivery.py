from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .identity import canonical


class DeliveryJournal:
    """Durable delivery receipts. A crash in the acceptance window is explicit, never replayed."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def accept(self, delivery_id: str, payload: dict, enqueue) -> dict:
        digest = hashlib.sha256(canonical(payload)).hexdigest()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT digest, result FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
            if row is not None:
                if row[0] != digest:
                    raise ValueError("message_id was already used for different content.")
                if row[1] is None:
                    raise RuntimeError("Prior delivery outcome is unknown. Check the target conversation; it will not be replayed.")
                return {**json.loads(row[1]), "duplicate": True}
            db.execute("INSERT INTO deliveries (id,digest) VALUES (?,?)", (delivery_id, digest))
        # Persist the intent before the side effect. An uncertain outcome remains recorded.
        result = enqueue()
        with self.connect() as db:
            db.execute("UPDATE deliveries SET result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), delivery_id))
        return result
