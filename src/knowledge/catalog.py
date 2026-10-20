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
        if 'generation' not in {row[1] for row in db.execute('PRAGMA table_info(libraries)')}:
            db.execute('ALTER TABLE libraries ADD COLUMN generation INTEGER NOT NULL DEFAULT 0')
        db.execute('CREATE TABLE IF NOT EXISTS index_configs('
                   'library_id TEXT NOT NULL,generation INTEGER NOT NULL,config TEXT NOT NULL,'
                   'PRIMARY KEY(library_id,generation))')
        # Rename the persisted visibility setting once, including archived configs.
        # Runtime contracts accept only allow_mcp; no legacy request alias is kept.
        for table in ('libraries', 'index_configs'):
            db.execute(f"UPDATE {table} SET config=json_remove("
                       "json_set(config,'$.allow_mcp',json(config -> '$.allow_agents')),'$.allow_agents') "
                       "WHERE json_type(config,'$.allow_agents') IS NOT NULL "
                       "AND json_type(config,'$.allow_mcp') IS NULL")
        db.commit()
        return db

    def list(self) -> list[dict]:
        with closing(self.connect()) as db:
            return [self.public(key, LibraryConfig.model_validate_json(raw), generation)
                    for key, raw, generation in db.execute("SELECT id,config,generation FROM libraries ORDER BY rowid")]

    def get(self, key: str) -> LibraryConfig:
        return self.resolve(key)[0]

    def resolve(self, key: str) -> tuple[LibraryConfig, Path]:
        """Read configuration and its index generation from one catalog snapshot."""
        with closing(self.connect()) as db:
            row = db.execute("SELECT config,generation FROM libraries WHERE id=?", (key,)).fetchone()
        if row is None:
            raise KeyError("知识库不存在")
        directory = self.workspace / "data" / "knowledge" / key
        if row[1]:
            directory = directory / 'generations' / str(row[1])
        return LibraryConfig.model_validate_json(row[0]), directory

    def create(self, config: LibraryConfig) -> dict:
        config = config.model_copy(update={"folder": checked_folder(config.folder)})
        key = uuid.uuid4().hex
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO libraries(id,config) VALUES(?,?)", (key, config.model_dump_json()))
        return self.public(key, config)

    def update(self, key: str, update: LibraryUpdate) -> dict:
        previous = self.get(key)
        raw = update.model_dump()
        if raw["api_key_alias"] is None:
            raw["api_key_alias"] = previous.api_key_alias
        raw['folder'] = checked_folder(raw['folder'])
        config = LibraryConfig.model_validate(raw)
        # Configuration remains editable. A different embedding/chunk space gets
        # a fresh directory; prior generations stay intact for recovery.
        index_fields = ('folder', 'dimensions', 'chunk_size', 'chunk_overlap', 'spreadsheet_header_row')
        index_changed = config.embedding_identity != previous.embedding_identity or any(
            getattr(config, field) != getattr(previous, field) for field in index_fields)
        with closing(self.connect()) as db, db:
            if index_changed:
                db.execute('INSERT OR REPLACE INTO index_configs SELECT id,generation,config FROM libraries WHERE id=?', (key,))
            db.execute("UPDATE libraries SET config=?,generation=generation+? WHERE id=?",
                       (config.model_dump_json(), int(index_changed), key))
            generation = db.execute('SELECT generation FROM libraries WHERE id=?', (key,)).fetchone()[0]
        return {**self.public(key, config, generation), 'index_changed': index_changed}

    def directory(self, key: str) -> Path:
        return self.resolve(key)[1]

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
    def public(key: str, config: LibraryConfig, generation: int = 0) -> dict:
        return {"id": key, **config.model_dump(), "has_api_key": bool(config.api_key_alias), 'index_generation': generation}
