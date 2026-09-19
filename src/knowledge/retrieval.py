import json

from .database import Database
from .embedding import Embedder
from .text import match_query
from .vectors import VectorIndex


def search(store: Database, config, query: str, limit: int = 10, mode: str = "hybrid", embedder=None, *, workspace=None):
    if mode not in {"hybrid", "semantic", "keyword"} or type(limit) is not int or not 1 <= limit <= 30:
        raise ValueError("invalid search mode or limit")
    if not isinstance(query, str) or not query.strip() or len(query) > 2000:
        raise ValueError("query must contain 1..2000 characters")
    candidates = max(limit * 10, 100)
    ranks: dict[int, float] = {}
    channels: dict[int, list[str]] = {}
    lists = []
    if mode in {"hybrid", "semantic"}:
        vector = (embedder or Embedder(config, workspace=workspace)).embed([query])[0]
        results = VectorIndex(store.directory, config.dimensions, readonly=True).search(vector, candidates)
        lists.append(("semantic", [row["id"] for row in results]))
    if mode in {"hybrid", "keyword"}:
        with store.connect() as db:
            results = db.execute("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ? ORDER BY rank LIMIT ?",
                                 (match_query(query), candidates)).fetchall()
        lists.append(("keyword", [row[0] for row in results]))
    for channel, ids in lists:
        for rank, key in enumerate(ids, 1):
            ranks[key] = ranks.get(key, 0) + 1 / (60 + rank)
            channels.setdefault(key, []).append(channel)
    hits = []
    with store.connect() as db:
        for key in sorted(ranks, key=lambda key: (-ranks[key], key)):
            row = db.execute("SELECT c.id AS chunk_id,c.document_id,c.text,c.page,c.line,c.location,d.path,d.warning,"
                             "d.state AS document_state FROM chunks c JOIN documents d ON d.id=c.document_id "
                             "WHERE c.id=? AND c.active=1", (key,)).fetchone()
            if row:
                hits.append({**dict(row), "location": json.loads(row["location"]), "score": ranks[key], "channels": channels[key]})
            if len(hits) == limit:
                break
    status = store.status()
    return {"query": query, "mode": mode, "matches": hits, "index_status": status["status"],
            "coverage": status["documents"], "partial": status["status"] != "completed"}


def read_chunk(store: Database, chunk_id: int):
    with store.connect() as db:
        row = db.execute("SELECT c.id AS chunk_id,c.document_id,c.text,c.page,c.line,c.location,d.path,d.warning "
                         "FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.id=? AND c.active=1",
                         (chunk_id,)).fetchone()
    if row is None:
        raise KeyError("片段不存在或已经被更新，请重新检索")
    return {**dict(row), "location": json.loads(row["location"])}
