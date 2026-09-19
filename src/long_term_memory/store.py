from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .contracts import Source, encode
from .privacy import redact
from .artifacts import prune_generations


class MemoryStore:
    """One node owns one database. Publications use a revision fence and immutable files."""

    def __init__(self, node_dir: Path, graph_id: str, node_id: str):
        if not graph_id or not node_id:
            raise ValueError("memory requires graph_id and node_id")
        self.node_dir = Path(node_dir).resolve()
        self.root = self.node_dir / "long_term_memory"
        if self.root.is_symlink():
            raise ValueError("memory root cannot be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "state.sqlite3"
        self.graph_id, self.node_id = graph_id, node_id
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO owner VALUES(1,?,?,1,0,NULL)", (graph_id, node_id))
            owner = db.execute("SELECT graph_id,node_id,schema_version FROM owner").fetchone()
            if tuple(owner) != (graph_id, node_id, 1):
                raise ValueError("memory database owner or schema mismatch")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    def sync(self, sources: list[Source]) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = {r["id"]: r["fingerprint"] for r in db.execute("SELECT id,fingerprint FROM sources")}
            suppressed = {r[0] for r in db.execute("SELECT id FROM suppressed")}
            current = {s.id: s for s in sources if s.id not in suppressed}
            removed = set(old) - set(current)
            changed = {key for key in set(old) & set(current) if old[key] != current[key].fingerprint}
            added = set(current) - set(old)
            for key in removed | changed:
                db.execute("DELETE FROM sources WHERE id=?", (key,))
            for key in changed | added:
                source = current[key]
                db.execute("INSERT INTO sources(id,trace_id,fingerprint,updated_at,payload,complete) VALUES(?,?,?,?,?,?)",
                           (source.id, source.trace_id, source.fingerprint, source.updated_at, redact(encode(source.records)), source.complete))
            if removed or changed or added:
                db.execute("UPDATE owner SET revision=revision+1")
            if removed or changed:
                db.execute("UPDATE owner SET publication=NULL")
                prune_generations(self.root, None)

    def state(self) -> dict:
        with self.connect() as db:
            return dict(db.execute("SELECT * FROM owner").fetchone())

    def selected(self, *, limit: int, cutoff: float, byte_budget: int) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("""SELECT * FROM sources WHERE status='succeeded' AND summary<>'' AND id NOT IN (SELECT id FROM suppressed)
                AND COALESCE(last_used,updated_at)>=? ORDER BY usage_count DESC,
                COALESCE(last_used,updated_at) DESC, id LIMIT ?""", (cutoff, limit)).fetchall()
        selected, size = [], 0
        for row in rows:
            entry = {k: row[k] for k in ("id", "trace_id", "fingerprint", "updated_at", "summary")}
            size += len(encode(entry).encode("utf-8"))
            if size > byte_budget:
                break
            selected.append(entry)
        return sorted(selected, key=lambda row: (row["updated_at"], row["id"]))

    def notes(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT id,content,created_at FROM notes ORDER BY created_at,id")]

    def add_note(self, content: str) -> str:
        import uuid
        if not isinstance(content, str) or not content.strip() or len(content.encode("utf-8")) > 6000:
            raise ValueError("memory note must contain 1..6000 UTF-8 bytes")
        key = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO notes VALUES(?,?,?)", (key, redact(content.strip()), time.time()))
            db.execute("UPDATE owner SET revision=revision+1,publication=NULL")
            prune_generations(self.root, None)
        return key

    def source(self, source_id: str, *, cutoff: float = 0) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
            if row is None or (row['last_used'] or row['updated_at']) < cutoff or db.execute(
                    "SELECT 1 FROM suppressed WHERE id=?", (source_id,)).fetchone():
                raise ValueError("memory source does not exist in this node")
            db.execute("UPDATE sources SET usage_count=usage_count+1,last_used=? WHERE id=?", (time.time(), source_id))
            return dict(row)

    def forget_source(self, source_id: str) -> None:
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone():
                raise ValueError("memory source does not exist in this node")
            db.execute("INSERT OR IGNORE INTO suppressed VALUES(?)", (source_id,))
            db.execute("UPDATE sources SET summary='',payload='[]',status='forgotten' WHERE id=?", (source_id,))
            db.execute("UPDATE owner SET revision=revision+1,publication=NULL")
            prune_generations(self.root, None)

    def publication(self) -> dict | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")  # Serialize artifact reads with publication/cleanup.
            key = db.execute("SELECT publication FROM owner").fetchone()[0]
            if key is None:
                return None
            folder = self.root / "generations" / key
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            return {"key": key, "manifest": manifest, "summary": (folder / "memory_summary.md").read_text(encoding="utf-8")}

    def invalidate(self, *, reset: bool = False) -> None:
        with self.connect() as db:
            db.execute("UPDATE owner SET revision=revision+1,publication=NULL")
            if reset:
                db.execute("DELETE FROM sources")
                db.execute("DELETE FROM notes")
            prune_generations(self.root, None)


def invalidate_node_memory(node_dir: str, *, reset: bool = False) -> None:
    path = Path(node_dir) / "long_term_memory" / "state.sqlite3"
    if not path.exists():
        return
    db = sqlite3.connect(path, timeout=30)
    try:
        with db:
            db.execute("UPDATE owner SET revision=revision+1,publication=NULL")
            if reset:
                db.execute("DELETE FROM sources")
                db.execute("DELETE FROM notes")
            prune_generations(path.parent, None)
    finally:
        db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS owner(singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 graph_id TEXT NOT NULL,node_id TEXT NOT NULL,schema_version INTEGER NOT NULL,
 revision INTEGER NOT NULL,publication TEXT);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,trace_id TEXT NOT NULL,fingerprint TEXT NOT NULL,
 updated_at REAL NOT NULL,payload TEXT NOT NULL,complete INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',summary TEXT NOT NULL DEFAULT '',slug TEXT NOT NULL DEFAULT '',
 retry_at REAL NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,error TEXT NOT NULL DEFAULT '',
 usage_count INTEGER NOT NULL DEFAULT 0,last_used REAL);
CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY,content TEXT NOT NULL,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS suppressed(id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS jobs(name TEXT PRIMARY KEY,token TEXT NOT NULL,lease_until REAL NOT NULL,
 retry_at REAL NOT NULL DEFAULT 0,status TEXT NOT NULL,error TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,started_at REAL NOT NULL,finished_at REAL,
 status TEXT NOT NULL,details TEXT NOT NULL DEFAULT '{}');
"""
