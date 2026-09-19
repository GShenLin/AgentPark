"""Crash-isolated, single-writer library pipeline; source files are never modified."""
import time
from pathlib import Path

from .catalog import Catalog
from .database import Database
from .embedding import Embedder
from .indexer import embed_pending
from .pipeline import ParseAhead
from .scanner import Interrupted, check_stop, prune, scan


def run_pipeline(workspace: str, key: str, stop):
    catalog = Catalog(Path(workspace))
    config = catalog.get(key)
    store = Database(catalog.directory(key))
    store.initialize()
    try:
        with store.connect() as db:
            db.execute("UPDATE job SET status='running',error='',updated_at=? WHERE id=1", (time.time(),))
        phase = store.status()["phase"]
        if phase == "scan":
            scan(store, Path(config.folder), stop)
            phase = "prune"
        if phase == "prune":
            prune(store, stop)
        with store.connect() as db:
            db.execute("UPDATE job SET phase='pipeline' WHERE id=1")
        with ParseAhead(store, config, stop) as parser:
            # Parsing continues during dimension detection, HTTP requests and
            # rate-limit waits. Only this thread writes the vector index.
            dimensions = Embedder(config, workspace=catalog.workspace, stop=parser.stop).detect_dimensions()
            config = catalog.bind_dimensions(key, dimensions)
            embedder = Embedder(config, workspace=catalog.workspace, stop=parser.stop)
            while True:
                check_stop(parser.stop)
                embed_pending(store, config, parser.stop, embedder)
                if parser.finished():
                    break
                parser.stop.wait(0.1)
        with store.connect() as db:
            failures = db.execute("SELECT count FROM counters WHERE kind='documents' AND state='error'").fetchone()
            status = "completed_with_errors" if failures and failures[0] else "completed"
            db.execute("UPDATE job SET status=?,phase='idle',current_path='',updated_at=? WHERE id=1", (status, time.time()))
    except Interrupted:
        with store.connect() as db:
            db.execute("UPDATE job SET status='paused',updated_at=? WHERE id=1", (time.time(),))
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        with store.connect() as db:
            db.execute("UPDATE job SET status='failed',error=?,updated_at=? WHERE id=1", (message[:2000], time.time()))
