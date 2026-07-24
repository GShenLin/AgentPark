from __future__ import annotations

import hashlib
import mimetypes
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from src.web_backend import runtime_paths


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LongTermMemoryAsset:
    id: str
    memory_id: str
    filename: str
    media_type: str
    byte_size: int
    sha256: str
    data: bytes


@dataclass(frozen=True)
class LongTermMemoryRecord:
    id: str
    graph_id: str
    node_id: str
    kind: str
    content: str
    summary: str = ""
    keywords: tuple[str, ...] = ()
    source_trace_id: str = ""
    status: str = "active"
    created_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))


class SqliteLongTermMemoryStore:
    """Canonical long-term memory store for one AgentPark node.

    SQLite owns structured memories and binary attachments. Markdown files such as
    User.md and Soul.md remain deliberately separate instruction documents.
    """

    def __init__(self, graph_id: str, node_id: str, *, path: str | None = None) -> None:
        self.graph_id = str(graph_id or "").strip()
        self.node_id = str(node_id or "").strip()
        if not self.graph_id or not self.node_id:
            raise ValueError("graph_id and node_id are required")
        self.path = path or os.path.join(runtime_paths._get_graphs_dir(), self.graph_id, self.node_id, "long_term_memory.sqlite3")
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._initialize()

    def add_memory(
        self,
        *,
        kind: str,
        content: str,
        summary: str = "",
        keywords: Iterable[str] = (),
        source_trace_id: str = "",
        memory_id: str | None = None,
    ) -> LongTermMemoryRecord:
        record = LongTermMemoryRecord(
            id=memory_id or f"mem_{uuid.uuid4().hex}",
            graph_id=self.graph_id,
            node_id=self.node_id,
            kind=_required_text(kind, "kind"),
            content=_required_text(content, "content"),
            summary=str(summary or "").strip(),
            keywords=tuple(dict.fromkeys(_required_text(item, "keyword") for item in keywords)),
            source_trace_id=str(source_trace_id or "").strip(),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memories (id, graph_id, node_id, kind, content, summary, source_trace_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record.id, record.graph_id, record.node_id, record.kind, record.content, record.summary, record.source_trace_id, record.status, record.created_at),
            )
            connection.executemany(
                "INSERT INTO memory_keywords (memory_id, keyword) VALUES (?, ?)",
                ((record.id, keyword) for keyword in record.keywords),
            )
        return record

    def add_asset(self, memory_id: str, filename: str, data: bytes, *, media_type: str | None = None) -> LongTermMemoryAsset:
        safe_memory_id = _required_text(memory_id, "memory_id")
        safe_filename = os.path.basename(_required_text(filename, "filename"))
        payload = bytes(data)
        if not payload:
            raise ValueError("asset data is required")
        asset = LongTermMemoryAsset(
            id=f"asset_{uuid.uuid4().hex}",
            memory_id=safe_memory_id,
            filename=safe_filename,
            media_type=str(media_type or mimetypes.guess_type(safe_filename)[0] or "application/octet-stream"),
            byte_size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            data=payload,
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO memory_assets (id, memory_id, filename, media_type, byte_size, sha256, data) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (asset.id, asset.memory_id, asset.filename, asset.media_type, asset.byte_size, asset.sha256, asset.data),
            )
        return asset

    def search(self, query: str, *, limit: int = 10) -> list[LongTermMemoryRecord]:
        terms = tuple(dict.fromkeys(part.casefold() for part in str(query or "").split() if part.strip()))
        if not terms:
            return []
        clauses = " OR ".join("LOWER(m.content) LIKE ? OR LOWER(m.summary) LIKE ? OR LOWER(k.keyword) LIKE ?" for _ in terms)
        params: list[object] = []
        for term in terms:
            pattern = f"%{term}%"
            params.extend((pattern, pattern, pattern))
        params.extend((self.graph_id, self.node_id, max(1, min(int(limit), 100))))
        sql = f"""
            SELECT DISTINCT m.id, m.graph_id, m.node_id, m.kind, m.content, m.summary,
                            m.source_trace_id, m.status, m.created_at
            FROM memories m
            LEFT JOIN memory_keywords k ON k.memory_id = m.id
            WHERE ({clauses}) AND m.graph_id = ? AND m.node_id = ? AND m.status = 'active'
            ORDER BY m.created_at DESC
            LIMIT ?
        """
        with self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
            output: list[LongTermMemoryRecord] = []
            for row in rows:
                keywords = tuple(item[0] for item in connection.execute("SELECT keyword FROM memory_keywords WHERE memory_id = ? ORDER BY keyword", (row[0],)))
                output.append(LongTermMemoryRecord(*row[:6], keywords, row[6], row[7], row[8]))
            return output

    def get_asset(self, asset_id: str) -> LongTermMemoryAsset | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, memory_id, filename, media_type, byte_size, sha256, data FROM memory_assets WHERE id = ?",
                (_required_text(asset_id, "asset_id"),),
            ).fetchone()
        return LongTermMemoryAsset(*row) if row else None

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS schema_meta (version INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    graph_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    source_trace_id TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(graph_id, node_id, status, created_at);
                CREATE TABLE IF NOT EXISTS memory_keywords (
                    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                    keyword TEXT NOT NULL,
                    PRIMARY KEY (memory_id, keyword)
                );
                CREATE INDEX IF NOT EXISTS idx_memory_keywords_keyword ON memory_keywords(keyword);
                CREATE TABLE IF NOT EXISTS memory_assets (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    byte_size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    data BLOB NOT NULL
                );
                """
            )
            row = connection.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
            if row is None:
                connection.execute("INSERT INTO schema_meta (version) VALUES (?)", (SCHEMA_VERSION,))
            elif int(row[0]) != SCHEMA_VERSION:
                raise RuntimeError(f"unsupported long-term memory schema version: {row[0]}")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text
