"""Bounded parse-ahead producer; the caller remains the sole vector writer."""
import threading
import time

from .parser import parse_pending
from .scanner import Interrupted, check_stop


MAX_PENDING_CHUNKS = 8192


class PipelineStop:
    def __init__(self, external):
        self.external = external
        self.local = threading.Event()

    def is_set(self):
        return self.local.is_set() or self.external.is_set()

    def wait(self, seconds):
        deadline = time.monotonic() + seconds
        while not self.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self.local.wait(min(remaining, 0.1))
        return True


class ParseAhead:
    def __init__(self, store, config, stop, *, max_pending_chunks=MAX_PENDING_CHUNKS):
        self.store, self.config = store, config
        self.stop = PipelineStop(stop)
        self.max_pending_chunks = max_pending_chunks
        self.done = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._run, name="knowledge-parser")

    def __enter__(self):
        self.thread.start()
        return self

    def _run(self):
        try:
            while True:
                check_stop(self.stop)
                with self.store.connect() as db:
                    pending = db.execute("SELECT 1 FROM documents WHERE state IN ('pending','parsing') LIMIT 1").fetchone()
                    queued = db.execute("SELECT count FROM counters WHERE kind='chunks' AND state='0'").fetchone()
                if pending is None:
                    return
                # Admission is per document. Finish the current document even if
                # it exceeds the cap: incomplete documents cannot be embedded.
                if queued is not None and queued[0] >= self.max_pending_chunks:
                    with self.store.connect() as db:
                        partial = db.execute("SELECT 1 FROM documents WHERE state='parsing' LIMIT 1").fetchone()
                    if partial is None:
                        self.stop.wait(0.1)
                        continue
                parse_pending(self.store, self.config, self.stop, document_limit=1)
        except Interrupted:
            pass
        except Exception as exc:
            self.error = exc
            self.stop.local.set()
        finally:
            self.done.set()

    def finished(self):
        if self.error is not None:
            raise self.error
        if not self.done.is_set():
            return False
        check_stop(self.stop)
        with self.store.connect() as db:
            return db.execute("SELECT 1 FROM documents WHERE state='embedding' LIMIT 1").fetchone() is None

    def __exit__(self, exc_type, exc, traceback):
        self.stop.local.set()
        self.thread.join()
        if self.error is not None:
            raise self.error
