"""Disk-backed directory frontier; a failed/incomplete scan never removes documents."""
import os
import time
from pathlib import Path

from .database import Database
from .document_types import EXTENSIONS




class Interrupted(Exception):
    pass


def check_stop(stop):
    if stop.is_set():
        raise Interrupted()


def begin_scan(store: Database):
    with store.connect() as db:
        db.execute("DELETE FROM directories")
        db.execute("INSERT INTO directories(path) VALUES('')")
        db.execute("UPDATE job SET generation=generation+1,phase='scan',status='queued',"
                   "discovered=0,excluded=0,current_path='',error='' WHERE id=1")


def scan(store: Database, folder: Path, stop):
    with store.connect() as db:
        generation = db.execute("SELECT generation FROM job").fetchone()[0]
    while True:
        check_stop(stop)
        with store.connect() as db:
            directory = db.execute("SELECT path FROM directories WHERE done=0 ORDER BY path LIMIT 1").fetchone()
        if directory is None:
            break
        relative = directory[0]
        # Replaying a directory after interruption is idempotent, including discovered counts.
        batch, subdirs, excluded = [], [], 0
        with os.scandir(folder / relative) as entries:
            for entry in entries:
                check_stop(stop)
                path = Path(entry.path)
                if entry.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                    excluded += 1
                elif entry.is_dir(follow_symlinks=False):
                    subdirs.append(path.relative_to(folder).as_posix())
                elif entry.is_file(follow_symlinks=False) and path.suffix.lower() in EXTENSIONS and not path.name.startswith("~$"):
                    info = entry.stat(follow_symlinks=False)
                    batch.append((path.relative_to(folder).as_posix(), info.st_size, info.st_mtime_ns, generation))
                if len(batch) + len(subdirs) >= 256:
                    _save(store, batch, subdirs, relative)
                    batch, subdirs = [], []
        _save(store, batch, subdirs, relative)
        with store.connect() as db:
            db.execute("UPDATE directories SET done=1 WHERE path=?", (relative,))
            db.execute("UPDATE job SET excluded=excluded+? WHERE id=1", (excluded,))
    # Only reached after every directory was successfully enumerated.
    with store.connect() as db:
        db.execute("UPDATE job SET phase='prune' WHERE id=1")


def _save(store, files, directories, current):
    with store.connect() as db:
        db.executemany("INSERT OR IGNORE INTO directories(path) VALUES(?)", ((p,) for p in directories))
        for path, size, mtime, generation in files:
            old = db.execute("SELECT seen FROM documents WHERE path=?", (path,)).fetchone()
            db.execute("""INSERT INTO documents(path,size,mtime_ns,seen) VALUES(?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET size=excluded.size,mtime_ns=excluded.mtime_ns,seen=excluded.seen,
                state=CASE WHEN documents.size<>excluded.size OR documents.mtime_ns<>excluded.mtime_ns
                THEN 'pending' ELSE documents.state END""", (path, size, mtime, generation))
            if old is None or old[0] != generation:
                db.execute("UPDATE job SET discovered=discovered+1 WHERE id=1")
        db.execute("UPDATE job SET current_path=?,updated_at=? WHERE id=1", (current, time.time()))


def prune(store: Database, stop):
    while True:
        check_stop(stop)
        with store.connect() as db:
            rows = db.execute("SELECT id FROM documents WHERE seen<(SELECT generation FROM job) LIMIT 100").fetchall()
            if not rows:
                db.execute("UPDATE job SET phase='parse' WHERE id=1")
                return
            for row in rows:
                db.execute("DELETE FROM chunks WHERE document_id=?", (row[0],))
                db.execute("DELETE FROM documents WHERE id=?", (row[0],))
