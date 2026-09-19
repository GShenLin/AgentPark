import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from .contracts import LibraryConfig, LibraryUpdate, checked_folder


class Catalog:
    """Owner-only configuration; secrets never enter public payloads or skill output."""

    def __init__(self, workspace: Path):
        self.workspace = Path(workspace)
        self.path = self.workspace / ".auth" / "knowledge.sqlite3"

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        db.execute("CREATE TABLE IF NOT EXISTS libraries(id TEXT PRIMARY KEY, config TEXT NOT NULL)")
        db.commit()
        return db

    def list(self) -> list[dict]:
        with closing(self.connect()) as db:
            return [self.public(key, LibraryConfig.model_validate_json(raw))
                    for key, raw in db.execute("SELECT id,config FROM libraries ORDER BY rowid")]

    def get(self, key: str) -> LibraryConfig:
        with closing(self.connect()) as db:
            row = db.execute("SELECT config FROM libraries WHERE id=?", (key,)).fetchone()
        if row is None:
            raise KeyError("知识库不存在")
        return LibraryConfig.model_validate_json(row[0])

    def create(self, config: LibraryConfig) -> dict:
        config = config.model_copy(update={"folder": checked_folder(config.folder)})
        key = uuid.uuid4().hex
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO libraries VALUES(?,?)", (key, config.model_dump_json()))
        return self.public(key, config)

    def update(self, key: str, update: LibraryUpdate) -> dict:
        previous = self.get(key)
        raw = update.model_dump()
        if raw["api_key_alias"] is None:
            raw["api_key_alias"] = previous.api_key_alias
        config = LibraryConfig.model_validate(raw)
        # A library is an embedding space. Never mix model identities or chunk versions.
        immutable = ("folder", "embedding_url", "embedding_model", "dimensions", "chunk_size", "chunk_overlap", "spreadsheet_header_row")
        for field in immutable:
            if getattr(config, field) != getattr(previous, field):
                raise ValueError(f"{field} 创建后不可变更；请创建新知识库以建立独立索引")
        with closing(self.connect()) as db, db:
            db.execute("UPDATE libraries SET config=? WHERE id=?", (config.model_dump_json(), key))
        return self.public(key, config)

    def directory(self, key: str) -> Path:
        self.get(key)  # Resolve through catalog, never accept a caller-supplied directory.
        return self.workspace / "data" / "knowledge" / key

    def bind_dimensions(self, key: str, dimensions: int) -> LibraryConfig:
        """Called by the worker or idle service under its writer lock."""
        from .database import Database
        from .vectors import VectorIndex

        config = self.get(key)
        updated = LibraryConfig.model_validate({**config.model_dump(), "dimensions": dimensions})
        directory = self.directory(key)
        store = Database(directory)
        if dimensions != config.dimensions and store.path.exists():
            with store.connect() as db:
                if db.execute("SELECT 1 FROM chunks WHERE embedded=1 LIMIT 1").fetchone():
                    raise ValueError(f"模型实际返回 {dimensions} 维，已有索引为 {config.dimensions} 维；请创建新知识库重建索引")
        VectorIndex.bind_empty_dimensions(directory, dimensions)
        if dimensions != config.dimensions:
            with closing(self.connect()) as db, db:
                db.execute("UPDATE libraries SET config=? WHERE id=?", (updated.model_dump_json(), key))
        return updated

    @staticmethod
    def public(key: str, config: LibraryConfig) -> dict:
        return {"id": key, **config.model_dump(), "has_api_key": bool(config.api_key_alias)}
