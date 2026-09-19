import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS job (
 id INTEGER PRIMARY KEY CHECK(id=1), phase TEXT NOT NULL DEFAULT 'idle',
 status TEXT NOT NULL DEFAULT 'idle', generation INTEGER NOT NULL DEFAULT 0,
 discovered INTEGER NOT NULL DEFAULT 0, excluded INTEGER NOT NULL DEFAULT 0,
 current_path TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
 updated_at REAL NOT NULL DEFAULT 0);
INSERT OR IGNORE INTO job(id) VALUES(1);
CREATE TABLE IF NOT EXISTS directories(path TEXT PRIMARY KEY, done INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS directories_pending ON directories(done,path);
CREATE TABLE IF NOT EXISTS documents (
 id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, size INTEGER NOT NULL,
 mtime_ns INTEGER NOT NULL, seen INTEGER NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending', revision TEXT NOT NULL DEFAULT '',
 active_revision TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
 warning TEXT NOT NULL DEFAULT '', chunk_count INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS documents_state ON documents(state,id);
CREATE INDEX IF NOT EXISTS documents_seen ON documents(seen,id);
CREATE TABLE IF NOT EXISTS chunks (
 id INTEGER PRIMARY KEY AUTOINCREMENT, document_id INTEGER NOT NULL REFERENCES documents(id),
 revision TEXT NOT NULL, ordinal INTEGER NOT NULL, page INTEGER, line INTEGER,
 text TEXT NOT NULL, tokens TEXT NOT NULL, location TEXT NOT NULL DEFAULT '{}', embedded INTEGER NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 0, UNIQUE(document_id,revision,ordinal));
CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id,revision,id);
CREATE INDEX IF NOT EXISTS chunks_document_pending ON chunks(document_id,revision,embedded);
CREATE INDEX IF NOT EXISTS chunks_pending ON chunks(embedded,id);
CREATE TABLE IF NOT EXISTS publications(id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS counters(kind TEXT NOT NULL, state TEXT NOT NULL, count INTEGER NOT NULL,
 PRIMARY KEY(kind,state));
CREATE TRIGGER IF NOT EXISTS documents_count_insert AFTER INSERT ON documents BEGIN
 INSERT INTO counters VALUES('documents',new.state,1) ON CONFLICT(kind,state) DO UPDATE SET count=count+1;
END;
CREATE TRIGGER IF NOT EXISTS documents_count_delete AFTER DELETE ON documents BEGIN
 UPDATE counters SET count=count-1 WHERE kind='documents' AND state=old.state;
END;
CREATE TRIGGER IF NOT EXISTS documents_count_update AFTER UPDATE OF state ON documents WHEN old.state<>new.state BEGIN
 UPDATE counters SET count=count-1 WHERE kind='documents' AND state=old.state;
 INSERT INTO counters VALUES('documents',new.state,1) ON CONFLICT(kind,state) DO UPDATE SET count=count+1;
END;
CREATE TRIGGER IF NOT EXISTS chunks_count_insert AFTER INSERT ON chunks BEGIN
 INSERT INTO counters VALUES('chunks',CAST(new.embedded AS TEXT),1) ON CONFLICT(kind,state) DO UPDATE SET count=count+1;
END;
CREATE TRIGGER IF NOT EXISTS chunks_count_delete AFTER DELETE ON chunks BEGIN
 UPDATE counters SET count=count-1 WHERE kind='chunks' AND state=CAST(old.embedded AS TEXT);
END;
CREATE TRIGGER IF NOT EXISTS chunks_count_update AFTER UPDATE OF embedded ON chunks WHEN old.embedded<>new.embedded BEGIN
 UPDATE counters SET count=count-1 WHERE kind='chunks' AND state=CAST(old.embedded AS TEXT);
 INSERT INTO counters VALUES('chunks',CAST(new.embedded AS TEXT),1) ON CONFLICT(kind,state) DO UPDATE SET count=count+1;
END;
CREATE TABLE IF NOT EXISTS garbage(id INTEGER PRIMARY KEY);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(tokens, content='chunks', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS chunks_publish AFTER UPDATE OF active ON chunks
WHEN new.active=1 AND old.active=0 BEGIN
 INSERT INTO chunk_fts(rowid,tokens) VALUES(new.id,new.tokens);
 INSERT OR IGNORE INTO publications(id) VALUES(new.id);
END;
CREATE TRIGGER IF NOT EXISTS chunks_unpublish AFTER UPDATE OF active ON chunks
WHEN new.active=0 AND old.active=1 BEGIN
 INSERT INTO chunk_fts(chunk_fts,rowid,tokens) VALUES('delete',old.id,old.tokens);
END;
CREATE TRIGGER IF NOT EXISTS chunks_delete BEFORE DELETE ON chunks BEGIN
 INSERT INTO garbage(id) VALUES(old.id);
 DELETE FROM publications WHERE id=old.id;
END;
CREATE TRIGGER IF NOT EXISTS chunks_delete_fts BEFORE DELETE ON chunks WHEN old.active=1 BEGIN
 INSERT INTO chunk_fts(chunk_fts,rowid,tokens) VALUES('delete',old.id,old.tokens);
END;
"""


class Database:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.path = self.directory / "index.sqlite3"

    def initialize(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            # Additive migration preserves existing vectors and published chunks.
            db.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in db.execute("PRAGMA table_info(chunks)")}
            if "location" not in columns:
                db.execute("ALTER TABLE chunks ADD COLUMN location TEXT NOT NULL DEFAULT '{}'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA cache_size=-16384")
            with db:
                yield db
        finally:
            db.close()

    def status(self) -> dict:
        with self.connect() as db:
            job = dict(db.execute("SELECT * FROM job WHERE id=1").fetchone())
            job["documents"] = dict(db.execute("SELECT state,count FROM counters WHERE kind='documents'"))
            job["chunks"] = dict(db.execute("SELECT state,count FROM counters WHERE kind='chunks'"))
            job["index_bytes"] = self.path.stat().st_size
        return job

    def documents(self, after: int = 0, state: str = "", limit: int = 50) -> dict:
        with self.connect() as db:
            rows = db.execute("SELECT id,path,state,error,warning,chunk_count FROM documents "
                              "WHERE id>? " + ("AND state=? " if state else "") + "ORDER BY id LIMIT ?",
                              (after, state, limit + 1) if state else (after, limit + 1)).fetchall()
        return {"items": [dict(row) for row in rows[:limit]],
                "next_cursor": rows[limit - 1]["id"] if len(rows) > limit else None}

    def publish(self, db, document_id: int, revision: str):
        db.execute("UPDATE chunks SET active=0 WHERE document_id=? AND active=1", (document_id,))
        db.execute("UPDATE chunks SET active=1 WHERE document_id=? AND revision=?", (document_id, revision))
        db.execute("UPDATE documents SET active_revision=?,state='ready',error='' WHERE id=?", (revision, document_id))
        db.execute("DELETE FROM chunks WHERE document_id=? AND revision<>?", (document_id, revision))
