"""Android vector storage: transactional SQLite with bounded-memory exact cosine search.

Uses a separate format, and refuses to hide an existing Lance index. Search scans
published vectors on disk; only the best `limit` results are retained in memory.
"""
from contextlib import closing, contextmanager
import heapq
import json
import math
from pathlib import Path
import sqlite3


class SQLiteVectorIndex:
    @staticmethod
    def _path(directory: Path) -> Path:
        lance = directory / "vectors"
        if lance.exists() and any(lance.iterdir()):
            raise ValueError("Android 无法读取已有 LanceDB 索引；请创建新知识库重建索引")
        return directory / "vectors.sqlite3"

    @staticmethod
    def bind_empty_dimensions(directory: Path, dimensions: int):
        path = SQLiteVectorIndex._path(directory)
        if not path.exists():
            return
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT dimensions FROM metadata WHERE id=1").fetchone()[0]
            if current == dimensions:
                return
            if db.execute("SELECT count(*) FROM chunks").fetchone()[0]:
                raise ValueError(f"模型实际返回 {dimensions} 维，已有向量为 {current} 维；请创建新知识库重建索引")
            db.execute("UPDATE metadata SET dimensions=? WHERE id=1", (dimensions,))

    def __init__(self, directory: Path, dimensions: int, *, readonly=False):
        self.path = self._path(directory)
        self.dimensions = dimensions
        self.readonly = readonly
        if not readonly:
            with self._connect() as db:
                db.execute("CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY CHECK(id=1), dimensions INTEGER NOT NULL)")
                db.execute("INSERT OR IGNORE INTO metadata VALUES(1, ?)", (dimensions,))
                db.execute("CREATE TABLE IF NOT EXISTS chunks (id INTEGER PRIMARY KEY, vector TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0)")
        with self._connect() as db:
            self._validate_dimensions(db)

    @contextmanager
    def _connect(self):
        uri = self.path.resolve().as_uri() + ("?mode=ro" if self.readonly else "?mode=rwc")
        with closing(sqlite3.connect(uri, uri=True, timeout=30)) as db, db:
            yield db

    def _validate_dimensions(self, db):
        if db.execute("SELECT dimensions FROM metadata WHERE id=1").fetchone()[0] != self.dimensions:
            raise ValueError("向量索引维度或数据结构不一致")

    def _normalize(self, vector):
        values = [float(value) for value in vector]
        if len(values) != self.dimensions or not all(math.isfinite(value) for value in values):
            raise ValueError("向量维度不一致或包含非有限数值")
        norm = math.hypot(*values)
        if norm == 0 or not math.isfinite(norm):
            raise ValueError("向量范数必须为有限正数")
        return [value / norm for value in values]

    def put(self, ids, vectors):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._validate_dimensions(db)
            db.executemany(
                "INSERT INTO chunks(id,vector,active) VALUES(?,?,0) "
                "ON CONFLICT(id) DO UPDATE SET vector=excluded.vector,active=0",
                ((int(key), json.dumps(self._normalize(vector), allow_nan=False))
                 for key, vector in zip(ids, vectors, strict=True)),
            )

    def delete(self, ids):
        with self._connect() as db:
            db.executemany("DELETE FROM chunks WHERE id=?", ((int(key),) for key in ids))

    def publish(self, ids):
        with self._connect() as db:
            db.executemany("UPDATE chunks SET active=1 WHERE id=?", ((int(key),) for key in ids))

    def search(self, vector, limit=150):
        query = self._normalize(vector)
        with self._connect() as db:
            self._validate_dimensions(db)
            rows = db.execute("SELECT id,vector FROM chunks WHERE active=1")
            scores = ((1.0 - sum(a * b for a, b in zip(query, json.loads(raw), strict=True)), key)
                      for key, raw in rows)
            return [{"id": key, "_distance": distance} for distance, key in heapq.nsmallest(limit, scores)]

    def count_rows(self):
        with self._connect() as db:
            return db.execute("SELECT count(*) FROM chunks").fetchone()[0]

    def maintain(self):
        with self._connect() as db:
            db.execute("PRAGMA optimize")
