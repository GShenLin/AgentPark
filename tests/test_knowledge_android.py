import threading

import pytest

from src.knowledge.vectors_sqlite import SQLiteVectorIndex


def test_vectors_persist_and_only_published_rows_are_searchable(tmp_path):
    index = SQLiteVectorIndex(tmp_path, 2)
    index.put([1, 2, 3], [[1, 0], [0, 1], [-1, 0]])
    index.publish([1, 3])
    reader = SQLiteVectorIndex(tmp_path, 2, readonly=True)
    assert [row["id"] for row in reader.search([2, 0])] == [1, 3]
    index.publish([2])
    assert [row["id"] for row in reader.search([0, 1], limit=1)] == [2]
    index.put([2], [[1, 1]])
    assert 2 not in [row["id"] for row in reader.search([0, 1])]
    index.publish([2])
    index.delete([1, 3])
    index.maintain()
    assert reader.count_rows() == 1
    assert reader.search([1, 1])[0]["_distance"] == pytest.approx(0)


def test_vector_batch_failure_rolls_back_and_dimensions_are_protected(tmp_path):
    index = SQLiteVectorIndex(tmp_path, 2)
    with pytest.raises(ValueError):
        index.put([1, 2], [[1, 0], [1, 0, 0]])
    assert index.count_rows() == 0
    with pytest.raises(ValueError):
        index.put([1, 2], [[1, 0]])
    assert index.count_rows() == 0
    SQLiteVectorIndex.bind_empty_dimensions(tmp_path, 3)
    with pytest.raises(ValueError):
        index.put([1], [[1, 0]])
    index = SQLiteVectorIndex(tmp_path, 3)
    index.put([1], [[1, 0, 0]])
    with pytest.raises(ValueError, match="已有向量"):
        SQLiteVectorIndex.bind_empty_dimensions(tmp_path, 2)
    with pytest.raises(ValueError):
        index.put([2], [[float("nan"), 0, 0]])
    assert index.count_rows() == 1


def test_existing_lance_data_is_not_silently_replaced(tmp_path):
    (tmp_path / "vectors").mkdir()
    (tmp_path / "vectors" / "chunks.lance").mkdir()
    with pytest.raises(ValueError, match="LanceDB"):
        SQLiteVectorIndex(tmp_path, 2)
    assert not (tmp_path / "vectors.sqlite3").exists()


def test_readonly_missing_index_is_not_created(tmp_path):
    import sqlite3
    with pytest.raises(sqlite3.OperationalError):
        SQLiteVectorIndex(tmp_path, 2, readonly=True)
    assert not (tmp_path / "vectors.sqlite3").exists()


def test_android_pdf_character_limit_and_cancellation(tmp_path, monkeypatch):
    pytest.importorskip("pypdf")
    from src.knowledge import parser
    from src.knowledge.contracts import LibraryConfig
    from src.knowledge.document_types import DocumentError
    from src.knowledge.scanner import Interrupted
    from tests.test_knowledge_pdf import minimal_pdf

    monkeypatch.setattr(parser.sys, "platform", "android")
    config = LibraryConfig(name="PDF", folder=str(tmp_path), embedding_url="http://localhost/v1/embeddings",
                           embedding_model="test", dimensions=8)
    path = tmp_path / "paper.pdf"
    path.write_bytes(minimal_pdf("Long text"))
    config = config.model_copy(update={"max_page_chars": 3})
    with pytest.raises(DocumentError, match="字符上限"):
        list(parser.passages(path, config, threading.Event(), []))
    stop = threading.Event()
    stop.set()
    with pytest.raises(Interrupted):
        list(parser.passages(path, config, stop, []))
