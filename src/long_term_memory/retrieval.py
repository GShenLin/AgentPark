from __future__ import annotations

import json
import re
import time

from .sources import load_sources
from .store import MemoryStore


class MemoryReader:
    def __init__(self, store: MemoryStore, max_unused_days: int = 30):
        self.store, self.max_unused_days = store, max_unused_days

    def refresh(self):
        self.store.sync(load_sources(self.store.node_dir))

    def summary(self) -> str:
        self.refresh()
        publication = self.store.publication()
        if not publication:
            return ""
        with self.store.connect() as db:
            active = {r["id"] for r in db.execute("SELECT id FROM sources WHERE COALESCE(last_used,updated_at)>=?",
                                                 (time.time() - self.max_unused_days * 86400,))}
        if not set(publication["manifest"]["sources"]) <= active:
            self.store.invalidate()
            return ""
        return publication["summary"]

    def search(self, query: str, limit: int = 10) -> dict:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("limit must be an integer between 1 and 20")
        self.refresh()
        with self.store.connect() as db:
            rows = db.execute("""SELECT id,trace_id,summary,updated_at FROM sources WHERE status='succeeded'
                AND COALESCE(last_used,updated_at)>=? ORDER BY updated_at DESC,id""",
                              (time.time() - self.max_unused_days * 86400,)).fetchall()
        hits = []
        for row in rows:
            lines = row["summary"].splitlines()
            matches = [(n + 1, line) for n, line in enumerate(lines) if query.casefold() in line.casefold()]
            if matches:
                hits.append({"source_id": row["id"], "trace_id": row["trace_id"],
                             "matches": [{"line": n, "text": text[:500]} for n, text in matches[:3]]})
        return {"matches": hits[:limit], "total": len(hits), "truncated": len(hits) > limit}

    def read(self, source_id: str, offset: int = 0, limit: int = 6000, evidence: bool = False) -> dict:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 12000:
            raise ValueError("offset must be >=0; limit must be 1..12000 characters")
        if type(evidence) is not bool:
            raise ValueError("evidence must be boolean")
        if not isinstance(source_id, str) or not re.fullmatch(r"[a-f0-9]{64}", source_id):
            raise ValueError("source_id must be the complete 64-character hex id, without memory: prefix")
        self.refresh()
        row = self.store.source(source_id, cutoff=time.time() - self.max_unused_days * 86400)
        text = json.dumps(json.loads(row["payload"]), ensure_ascii=False, indent=2) if evidence else row["summary"]
        if offset > len(text):
            raise ValueError("offset exceeds source length")
        end = min(offset + limit, len(text))
        return {"source_id": source_id, "trace_id": row["trace_id"], "source_fingerprint": row["fingerprint"],
                "content": text[offset:end], "next_offset": end if end < len(text) else None,
                "evidence": evidence, "status": row["status"]}
