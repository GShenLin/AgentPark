from .database import Database
from .scanner import check_stop
from .vectors import VectorIndex


def drain_garbage(store: Database, vectors: VectorIndex, stop):
    while True:
        check_stop(stop)
        with store.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM garbage ORDER BY id LIMIT 512")]
        if not ids:
            return
        vectors.delete(ids)
        with store.connect() as db:
            db.executemany("DELETE FROM garbage WHERE id=?", ((key,) for key in ids))


def embed_pending(store: Database, config, stop, embedder):
    vectors = VectorIndex(store.directory, config.dimensions)
    drain_garbage(store, vectors, stop)
    drain_publications(store, vectors, stop)
    since_maintenance = 0
    while True:
        check_stop(stop)
        with store.connect() as db:
            rows = db.execute("SELECT c.id,c.text,c.document_id FROM chunks c JOIN documents d ON d.id=c.document_id "
                              "WHERE c.embedded=0 AND d.state='embedding' ORDER BY c.id LIMIT 512").fetchall()
        if not rows:
            break
        # Checkpoint each API batch; this bounds repeated paid calls after a crash.
        for start in range(0, len(rows), config.batch_size):
            check_stop(stop)
            batch = rows[start:start + config.batch_size]
            embeddings = embedder.embed([row["text"] for row in batch])
            ids = [row["id"] for row in batch]
            # Upsert before SQLite checkpoint is repeatable after interruption.
            vectors.put(ids, embeddings)
            with store.connect() as db:
                db.executemany("UPDATE chunks SET embedded=1 WHERE id=?", ((key,) for key in ids))
            since_maintenance += len(batch)
        _publish_completed(store, {row["document_id"] for row in rows})
        drain_publications(store, vectors, stop)
        if since_maintenance >= 8192:
            check_stop(stop)
            vectors.maintain()
            since_maintenance = 0
    # Handles interruption after the final batch checkpoint but before publication.
    while True:
        check_stop(stop)
        with store.connect() as db:
            ready = db.execute("SELECT id FROM documents d WHERE state='embedding' AND NOT EXISTS "
                               "(SELECT 1 FROM chunks c WHERE c.document_id=d.id AND c.revision=d.revision "
                               "AND c.embedded=0) LIMIT 100").fetchall()
        if not ready:
            break
        _publish_completed(store, {row[0] for row in ready})
        drain_publications(store, vectors, stop)
    drain_garbage(store, vectors, stop)
    check_stop(stop)
    vectors.maintain()


def drain_publications(store, vectors, stop):
    while True:
        check_stop(stop)
        with store.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM publications ORDER BY id LIMIT 512")]
        if not ids:
            return
        vectors.publish(ids)
        with store.connect() as db:
            db.executemany("DELETE FROM publications WHERE id=?", ((key,) for key in ids))


def _publish_completed(store, ids):
    with store.connect() as db:
        for key in ids:
            row = db.execute("SELECT revision FROM documents WHERE id=? AND state='embedding'", (key,)).fetchone()
            if row and not db.execute("SELECT 1 FROM chunks WHERE document_id=? AND revision=? AND embedded=0 LIMIT 1",
                                      (key, row[0])).fetchone():
                store.publish(db, key, row[0])
