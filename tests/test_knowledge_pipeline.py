import threading
from pathlib import Path

import pytest

from src.knowledge.catalog import Catalog
from src.knowledge.contracts import LibraryConfig, LibraryUpdate
from src.knowledge.database import Database
from src.knowledge.embedding import EmbeddingError, validate_vectors
from src.knowledge.indexer import embed_pending
from src.knowledge.parser import parse_pending
from src.knowledge.retrieval import search, read_chunk
from src.knowledge.scanner import begin_scan, scan, prune, Interrupted
from src.knowledge.skill import execute


class TestEmbedder:
    __test__ = False

    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(texts)
        # Synonyms have the same direction; the test verifies actual vector retrieval.
        return [[1.0 if any(term in text.lower() for term in ('cat', 'feline', '猫')) else 0.0,
                 1.0 if 'physics' in text.lower() else 0.0, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0] for text in texts]


@pytest.fixture
def library(tmp_path):
    folder = tmp_path / "notes"
    folder.mkdir()
    catalog = Catalog(tmp_path)
    config = LibraryConfig(name="笔记", folder=str(folder), embedding_url="http://localhost:1111/v1/embeddings",
                           embedding_model="test", dimensions=8, allow_agents=True, batch_size=2, chunk_size=256, chunk_overlap=32)
    key = catalog.create(config)["id"]
    store = Database(catalog.directory(key))
    store.initialize()
    return catalog, key, config, store, threading.Event()


def ingest(library, embedder=None):
    _, _, config, store, stop = library
    begin_scan(store)
    scan(store, Path(config.folder), stop)
    prune(store, stop)
    parse_pending(store, config, stop, document_limit=1000)
    embed_pending(store, config, stop, embedder or TestEmbedder())


def test_real_hybrid_index_citations_and_incremental_update_delete(library):
    _, _, config, store, stop = library
    source = Path(config.folder) / "猫咪.md"
    source.write_text("# 猫咪\n猫咪喜欢阳光。Domestic cats sleep here.\n" * 20, encoding="utf-8")
    other = Path(config.folder) / "physics.md"
    other.write_text("Physics studies energy and matter.", encoding="utf-8")
    embedder = TestEmbedder()
    ingest(library, embedder)
    assert store.status()["documents"]["ready"] == 2
    assert all(len(batch) <= 2 for batch in embedder.calls)
    hits = search(store, config, "feline", mode="semantic", embedder=embedder)["matches"]
    assert hits[0]["path"] == "猫咪.md"
    assert hits[0]["line"] >= 1
    assert read_chunk(store, hits[0]["chunk_id"])["text"] == hits[0]["text"]
    assert search(store, config, "猫咪", mode="keyword")["matches"]
    calls = len(embedder.calls)
    ingest(library, embedder)
    assert len(embedder.calls) == calls  # unchanged files never call embedding again
    source.write_text("新的猫咪笔记 cats", encoding="utf-8")
    other.unlink()
    ingest(library, embedder)
    assert not search(store, config, "physics", mode="keyword")["matches"]
    assert search(store, config, "新的", mode="keyword")["matches"]
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM garbage").fetchone()[0] == 0


def test_failed_embedding_keeps_previous_publication_and_resumes(library):
    _, _, config, store, stop = library
    path = Path(config.folder) / "a.md"
    path.write_text("old cats", encoding="utf-8")
    ingest(library)
    path.write_text("new cats " * 100, encoding="utf-8")
    begin_scan(store); scan(store, Path(config.folder), stop); prune(store, stop); parse_pending(store, config, stop)

    class FailsAfterFirst(TestEmbedder):
        def embed(self, texts):
            if self.calls:
                raise EmbeddingError("offline")
            return super().embed(texts)

    with pytest.raises(EmbeddingError):
        embed_pending(store, config, stop, FailsAfterFirst())
    assert search(store, config, "old", mode="keyword")["matches"]
    assert not search(store, config, "new", mode="keyword")["matches"]
    remaining = TestEmbedder()
    embed_pending(store, config, stop, remaining)
    assert not search(store, config, "old", mode="keyword")["matches"]
    assert search(store, config, "new", mode="keyword")["matches"]
    with store.connect() as db:
        count = db.execute("SELECT count(*) FROM chunks").fetchone()[0]
    assert sum(map(len, remaining.calls)) == count - 2


def test_scan_interruption_and_unavailable_root_do_not_prune(library):
    _, _, config, store, stop = library
    folder = Path(config.folder)
    (folder / "a.md").write_text("preserve cats", encoding="utf-8")
    ingest(library)
    begin_scan(store)
    stop.set()
    with pytest.raises(Interrupted):
        scan(store, folder, stop)
    stop.clear()
    folder.rename(folder.with_name("offline"))
    with pytest.raises(FileNotFoundError):
        scan(store, folder, stop)
    assert search(store, config, "preserve", mode="keyword")["matches"]
    assert store.status()["phase"] == "scan"


def test_errors_are_visible_and_never_publish_partial_file(library):
    _, _, config, store, _ = library
    (Path(config.folder) / "bad.md").write_bytes(b"\xff\xfe\x80")
    (Path(config.folder) / "broken.pdf").write_bytes(b"not a PDF")
    ingest(library)
    result = store.documents(state="error")
    assert len(result["items"]) == 2
    assert all(item["error"] for item in result["items"])
    assert not search(store, config, "PDF", mode="keyword")["matches"]


def test_secret_redaction_visibility_and_immutable_embedding_space(library):
    catalog, key, config, _, _ = library
    update = LibraryUpdate(**{**config.model_dump(), "api_key_alias": "shared-key", "allow_agents": False})
    assert "api_key" not in catalog.update(key, update)
    assert execute(catalog.workspace, {"action": "list"}) == {"libraries": []}
    with pytest.raises(PermissionError):
        execute(catalog.workspace, {"action": "search", "library_id": key, "query": "test"})
    catalog.update(key, LibraryUpdate(**{**update.model_dump(), "api_key_alias": None}))
    assert catalog.get(key).api_key_alias == "shared-key"
    with pytest.raises(ValueError, match="dimensions"):
        catalog.update(key, LibraryUpdate(**{**update.model_dump(), "dimensions": 16}))


@pytest.mark.parametrize("payload", [
    {"data": []}, {"data": [{"index": 0, "embedding": [1.0]}]},
    {"data": [{"index": 0, "embedding": [float('nan')] * 8}]},
    {"data": [{"index": 0, "embedding": [0.0] * 8}]},
    {"data": [{"index": True, "embedding": [1.0] * 8}]},
])
def test_embedding_protocol_rejects_invalid_responses(payload):
    with pytest.raises(EmbeddingError):
        validate_vectors(payload, 1, 8)


def test_cursor_pagination_and_replayed_directory_counts(library):
    _, _, config, store, stop = library
    for index in range(270):
        (Path(config.folder) / f"{index:04}.md").write_text("note", encoding="utf-8")
    begin_scan(store)
    scan(store, Path(config.folder), stop)
    with store.connect() as db:
        db.execute("UPDATE directories SET done=0")
    scan(store, Path(config.folder), stop)
    assert store.status()["discovered"] == 270
    first = store.documents(limit=50)
    second = store.documents(after=first["next_cursor"], limit=50)
    assert len(first["items"]) == len(second["items"]) == 50
    assert {item["id"] for item in first["items"]}.isdisjoint(item["id"] for item in second["items"])


def test_single_skill_supports_list_search_and_read(library):
    catalog, key, config, _, _ = library
    (Path(config.folder) / "a.md").write_text("cats live here", encoding="utf-8")
    ingest(library)
    assert execute(catalog.workspace, {"action": "list"})["libraries"][0]["id"] == key
    result = execute(catalog.workspace, {"action": "search", "library_id": key, "query": "cats", "mode": "keyword"})
    hit = result["matches"][0]
    passage = execute(catalog.workspace, {"action": "read", "library_id": key, "chunk_id": hit["chunk_id"]})
    assert passage["text"] == hit["text"]


def test_dimension_binding_preserves_pending_chunks_and_rebuilds_only_empty_table(library):
    from src.knowledge.vectors import VectorIndex
    catalog, key, config, store, stop = library
    (Path(config.folder) / "a.md").write_text("cats live here", encoding="utf-8")
    begin_scan(store); scan(store, Path(config.folder), stop); prune(store, stop); parse_pending(store, config, stop)
    VectorIndex(store.directory, 8)
    updated = catalog.bind_dimensions(key, 16)
    assert updated.dimensions == catalog.get(key).dimensions == 16
    vectors = VectorIndex(store.directory, 16)
    assert vectors.table.count_rows() == 0
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM chunks").fetchone()[0] == 1
    # A write before the SQLite checkpoint must also prohibit dimension changes.
    vectors.put([1], [[1.0] * 16])
    with pytest.raises(ValueError, match="已有向量"):
        catalog.bind_dimensions(key, 32)
    assert catalog.get(key).dimensions == 16
    assert vectors.table.count_rows() == 1


def test_published_index_dimension_cannot_change(library):
    catalog, key, config, _, _ = library
    (Path(config.folder) / "a.md").write_text("cats live here", encoding="utf-8")
    ingest(library)
    with pytest.raises(ValueError, match="已有索引"):
        catalog.bind_dimensions(key, 16)
    assert catalog.get(key).dimensions == 8
